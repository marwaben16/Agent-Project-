import os
import uuid
import sys
import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from pydantic import BaseModel, Field, conint, confloat

from azure.cosmos import CosmosClient, PartitionKey
from azure.cosmos.exceptions import CosmosResourceNotFoundError

from fastmcp import FastMCP

load_dotenv()

# Windows: reduce async/SSE shutdown issues
if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# -----------------------------
# Config Cosmos
# -----------------------------
COSMOS_ENDPOINT = os.environ["COSMOS_ENDPOINT"]
COSMOS_KEY = os.environ["COSMOS_KEY"]
COSMOS_DB = os.environ.get("COSMOS_DB", "poc-orders")

# Containers
ORDERS_CONTAINER = os.environ.get("COSMOS_ORDERS_CONTAINER", "orders")
CATALOG_CONTAINER = os.environ.get("COSMOS_CATALOG_CONTAINER", "catalog")
CUSTOMERS_CONTAINER = os.environ.get("COSMOS_CUSTOMERS_CONTAINER", "customers")

# Partition keys
ORDERS_PARTITION_KEY = os.environ.get("COSMOS_ORDERS_PARTITION_KEY", "/NumeroCommande")
CATALOG_PARTITION_KEY = os.environ.get("COSMOS_CATALOG_PARTITION_KEY", "/size_inch")
CUSTOMERS_PARTITION_KEY = os.environ.get("COSMOS_CUSTOMERS_PARTITION_KEY", "/phone")

# -----------------------------
# MCP instance
# -----------------------------
mcp = FastMCP("pneu-mcp-tools")

# -----------------------------
# Pydantic models
# -----------------------------
class OrderItem(BaseModel):
    ArticleName: str = Field(..., description="Nom de l'article commandé.")
    prix: confloat(gt=0) = Field(..., description="Prix unitaire en euros.")
    qty: conint(gt=0) = Field(1, description="Quantité commandée (>= 1).")


class ClientInfo(BaseModel):
    name: Optional[str] = Field(None, description="Nom du client.")
    phone: Optional[str] = Field(None, description="Téléphone du client.")
    city: Optional[str] = Field(None, description="Ville.")
    address: Optional[str] = Field(None, description="Adresse complète.")


class CreateOrderInput(BaseModel):
    """
    IMPORTANT:
    - confirmed doit être True pour créer la commande (sécurité: pas de création sans confirmation explicite)
    """
    client: ClientInfo = Field(default_factory=ClientInfo, description="Informations client.")
    items: List[OrderItem] = Field(..., min_length=1, description="Liste d'articles commandés.")
    notes: Optional[str] = Field(None, description="Notes / remarques.")
    confirmed: bool = Field(False, description="Doit être True si le client a confirmé la commande.")


class CreateOrderResult(BaseModel):
    NumeroCommande: str
    total: float
    currency: str = "EUR"


class OrderDocument(BaseModel):
    id: str
    NumeroCommande: str
    client: ClientInfo
    items: List[OrderItem]
    notes: Optional[str] = None
    status: str
    createdAt: str
    total: float
    currency: str = "EUR"


class CustomerUpsertInput(BaseModel):
    phone: str = Field(..., description="Numéro téléphone du client (ex: +336...).")
    name: Optional[str] = Field(None, description="Nom et prénom.")
    city: Optional[str] = Field(None, description="Ville.")
    address: Optional[str] = Field(None, description="Adresse complète.")


# -----------------------------
# Pydantic dump helper (v1/v2)
# -----------------------------
def _dump_model(obj: Any) -> Dict[str, Any]:
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    return obj.dict()

# -----------------------------
# Cosmos init
# -----------------------------
_cosmos_client = CosmosClient(COSMOS_ENDPOINT, credential=COSMOS_KEY)
_db = _cosmos_client.create_database_if_not_exists(COSMOS_DB)

orders_container = _db.create_container_if_not_exists(
    id=ORDERS_CONTAINER,
    partition_key=PartitionKey(path=ORDERS_PARTITION_KEY),
)

catalog_container = _db.create_container_if_not_exists(
    id=CATALOG_CONTAINER,
    partition_key=PartitionKey(path=CATALOG_PARTITION_KEY),
)

customers_container = _db.create_container_if_not_exists(
    id=CUSTOMERS_CONTAINER,
    partition_key=PartitionKey(path=CUSTOMERS_PARTITION_KEY),
)

# -----------------------------
# Helpers
# -----------------------------
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_order_number() -> str:
    return str(uuid.uuid4().int)[:8]


def calc_total(items: List[OrderItem]) -> float:
    return float(sum(i.prix * i.qty for i in items))


def get_pk_value(doc: Dict[str, Any], pk_path: str) -> Any:
    key = pk_path[1:] if pk_path.startswith("/") else pk_path
    return doc.get(key)


def safe_create(container, doc: Dict[str, Any], pk_path: str) -> None:
    """
    create_item compatible multi-versions azure-cosmos:
    - certaines versions supportent partition_key=...
    - d'autres non => fallback create_item(body=doc)
    """
    pk_value = get_pk_value(doc, pk_path)
    try:
        container.create_item(body=doc, partition_key=pk_value)
    except TypeError:
        container.create_item(body=doc)


def safe_read(container, item_id: str, pk_value: Any) -> Optional[Dict[str, Any]]:
    """
    read_item compatible multi-versions azure-cosmos:
    - essaye read_item(..., partition_key=pk_value)
    - fallback query SQL cross-partition si TypeError
    """
    try:
        return container.read_item(item=item_id, partition_key=pk_value)
    except CosmosResourceNotFoundError:
        return None
    except TypeError:
        q = "SELECT * FROM c WHERE c.id = @id"
        params = [{"name": "@id", "value": item_id}]
        items = list(
            container.query_items(
                query=q,
                parameters=params,
                enable_cross_partition_query=True,
            )
        )
        return items[0] if items else None


def normalize_phone(phone: str) -> str:
    # POC: normalize basic spaces. (In prod: use libphonenumber)
    return phone.strip().replace(" ", "")

# -----------------------------
# MCP TOOLS
# -----------------------------
@mcp.tool(
    description=(
        "Récupère le catalogue des pneus depuis Cosmos DB. "
        "Utiliser quand le client demande des produits disponibles, une taille (pouces), "
        "une marque, une saison ou un prix. Ne jamais inventer de produits/prix."
    )
)
def get_catalog(
    size_inch: Optional[int] = None,
    brand: Optional[str] = None,
    season: Optional[str] = None,
    active_only: bool = True,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    query = "SELECT * FROM c WHERE 1=1"
    params = []

    if active_only:
        query += " AND c.active = true"

    if size_inch is not None:
        query += " AND c.size_inch = @size"
        params.append({"name": "@size", "value": int(size_inch)})

    if brand:
        query += " AND LOWER(c.brand) = @brand"
        params.append({"name": "@brand", "value": brand.lower()})

    if season:
        query += " AND LOWER(c.season) = @season"
        params.append({"name": "@season", "value": season.lower()})

    query += " ORDER BY c.prix ASC OFFSET 0 LIMIT @limit"
    params.append({"name": "@limit", "value": int(limit)})

    return list(
        catalog_container.query_items(
            query=query,
            parameters=params,
            enable_cross_partition_query=True,
        )
    )


@mcp.tool(
    description=(
        "Recherche un client existant par numéro de téléphone dans Cosmos DB. "
        "À utiliser dès que le téléphone est connu pour éviter de redemander les coordonnées."
    )
)
def get_customer_by_phone(phone: str) -> Dict[str, Any]:
    phone = normalize_phone(phone)
    cust_id = f"CUST-{phone}"
    doc = safe_read(customers_container, cust_id, phone)
    if not doc:
        return {"exists": False, "phone": phone}
    return {"exists": True, "customer": doc}


@mcp.tool(
    description=(
        "Crée ou met à jour un client dans Cosmos DB (customers). "
        "À utiliser après avoir collecté les coordonnées d'un nouveau client."
    )
)
def upsert_customer(customer: CustomerUpsertInput) -> Dict[str, Any]:
    phone = normalize_phone(customer.phone)
    cust_id = f"CUST-{phone}"

    existing = safe_read(customers_container, cust_id, phone)
    now = now_iso()

    doc = {
        "id": cust_id,
        "type": "customer",
        "phone": phone,
        "name": customer.name,
        "city": customer.city,
        "address": customer.address,
        "updatedAt": now,
        "createdAt": (existing.get("createdAt") if existing else now),
    }

    # upsert_item is stable across azure-cosmos versions
    customers_container.upsert_item(doc)
    return {"status": "ok", "customer": doc}


@mcp.tool(
    description=(
        "Crée une commande CONFIRMÉE dans Cosmos DB (orders) et retourne NumeroCommande + total. "
        "Utiliser uniquement après confirmation explicite du client (order.confirmed=true)."
    )
)
def create_order(order: CreateOrderInput) -> Dict[str, Any]:
    if not order.confirmed:
        raise ValueError(
            "Commande non confirmée. Mettre confirmed=true uniquement après confirmation explicite du client."
        )

    numero = new_order_number()
    total = calc_total(order.items)

    doc = _dump_model(
        OrderDocument(
            id=f"CMD-{numero}",
            NumeroCommande=numero,
            client=order.client,
            items=order.items,
            notes=order.notes,
            status="CONFIRMED",
            createdAt=now_iso(),
            total=total,
        )
    )

    safe_create(orders_container, doc, ORDERS_PARTITION_KEY)

    return _dump_model(CreateOrderResult(NumeroCommande=numero, total=total))


@mcp.tool(
    description=(
        "Récupère une commande existante par NumeroCommande depuis Cosmos DB. "
        "Utile pour afficher un récapitulatif ou vérifier le statut."
    )
)
def get_order(NumeroCommande: str) -> Dict[str, Any]:
    item_id = f"CMD-{NumeroCommande}"
    doc = safe_read(orders_container, item_id, NumeroCommande)
    if not doc:
        return {"error": "NOT_FOUND", "NumeroCommande": NumeroCommande}
    return doc


@mcp.tool(
    description="Health check: confirme que le serveur MCP tourne et que Cosmos DB est accessible."
)
def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "time": now_iso(),
        "db": COSMOS_DB,
        "orders_container": ORDERS_CONTAINER,
        "catalog_container": CATALOG_CONTAINER,
        "customers_container": CUSTOMERS_CONTAINER,
    }


# -----------------------------
# Run server
# -----------------------------
if __name__ == "__main__":
    mcp.run(
        transport="http",
        host="0.0.0.0",
        log_level="debug",
        port=int(os.environ.get("PORT", "8000")),
    )
