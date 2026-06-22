# 🛞 Agent IA de commande de pneus

Un agent conversationnel qui joue le rôle d'une conseillère pneus virtuelle. Elle discute naturellement avec les clients, consulte le catalogue en temps réel depuis Cosmos DB, et crée des commandes confirmées — le tout via un serveur MCP maison.

---

## Ce que ça fait concrètement

Le projet tourne en deux parties :

**`server.py`** — un serveur MCP qui expose 6 outils :
- `get_catalog` — récupère les pneus disponibles avec filtres (taille, marque, saison, prix)
- `get_customer_by_phone` — cherche un client existant dans la base
- `upsert_customer` — crée ou met à jour un profil client
- `create_order` — enregistre une commande confirmée (avec garde-fou `confirmed=true`)
- `get_order` — consulte une commande existante par numéro
- `health` — vérifie que le serveur et Cosmos DB sont accessibles

**`agent.py`** — un agent conversationnel (Azure OpenAI + `agent_framework`) qui :
- utilise les outils MCP via HTTP 
- maintient un historique de conversation (avec AgentThread)
- se comporte comme une vraie conseillère

---

## Structure du projet

```
.
├── server.py         # Serveur MCP (outils Azure)
├── agent.py          # Agent vendeur (conversation client)
├── .env              # Variables d'environnement (non commité)
└── requirements.txt  # Packages Python
```

---

## Installation

### Prérequis

- Python 3.10+
- Un compte Azure avec :
  - Cosmos DB (NoSQL API)
  - Azure OpenAI déployé (ex: `gpt-4o`)

### Setup

```bash
pip install -r requirements.txt
```

Crée un fichier `.env` à la racine :

```env
# Cosmos DB
COSMOS_ENDPOINT=https://<compte>.documents.azure.com:443/
COSMOS_KEY=<clé-primaire>

# Optionnel — noms des containers (valeurs par défaut ci-dessous)
COSMOS_ORDERS_CONTAINER=orders
COSMOS_CATALOG_CONTAINER=catalog
COSMOS_CUSTOMERS_CONTAINER=customers

# Azure OpenAI (requis par agent_framework.azure)
AZURE_OPENAI_ENDPOINT=https://<endpoint>.openai.azure.com/
AZURE_OPENAI_API_KEY=<clé>
AZURE_OPENAI_DEPLOYMENT= <ton-déploiement>
AZURE_OPENAI_API_VERSION=<date> preview
```

---

## Lancement

### 1. Démarrer le serveur MCP

```bash
python server.py
# → Écoute sur http://0.0.0.0:8000/mcp
```

### 2. Lancer l'agent

Dans un autre terminal :

```bash
python agent.py
```

Tu obtiens un chat en ligne de commande. l'agent se présente et prend en charge le client.

```
🟢 Chat démarré. Tape 'exit' pour quitter.

Client > Bonjour

Agent > Bonjour 🙂 Je suis votre conseillère pneus.
        Vous pouvez me donner votre numéro de téléphone pour commencer ?
```

---

## Catalogue Cosmos — format attendu

Chaque document dans le container `catalog` doit ressembler à ça :

```json
{
  "id": "pneu-001",
  "brand": "Michelin",
  "model": "Pilot Sport 4",
  "size_inch": 17,
  "season": "summer",
  "prix": 129.90,
  "active": true
}
```

---



Projet personnel / POC — aucune licence particulière pour l'instant.
