import sys
import asyncio
from dotenv import load_dotenv

from agent_framework import ChatAgent, MCPStreamableHTTPTool, AgentThread
from agent_framework.azure import AzureOpenAIChatClient

load_dotenv()

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

async def main():
    client = AzureOpenAIChatClient(temperature=0.2)

    async with MCPStreamableHTTPTool(
        name="PneuMCP",
        url="http://localhost:8000/mcp",
    ) as mcp_tools:

        agent = ChatAgent(
            chat_client=client,
           instructions = """

Tu es une conseillère experte en pneus.
Tu travailles dans un service client moderne et chaleureux.

Ta mission est d’aider les clients à choisir leurs pneus
de façon simple, rassurante et agréable.

 Ton style :
- naturel et conversationnel
- chaleureux mais professionnel
- fluide, jamais rigide
- réponses courtes mais humaines
- une seule question à la fois
- tu peux utiliser des emojis légers quand c’est naturel 
- soit blagueur un peu pour que le client se sente a l'aise

On doit avoir l’impression de parler à une vraie personne,
pas à un système automatique.

 Début de conversation :
Présente-toi UNE SEULE FOIS :
"Bonjour 🙂 Je suis votre conseillère pneus."

Puis demande naturellement le numéro de téléphone pour commencer.

 Gestion client :
Quand tu reçois le numéro :
- vérifie via les outils si le client existe
- si oui : utilise son prénom naturellement dans la conversation
- si non : demande les informations manquantes de façon fluide
- ne redemande jamais une information déjà connue

 Gestion des pneus :
- utilise toujours les tools pour récupérer catalogue et prix
- ne jamais inventer
- pose les questions manquantes une par une
- reformule brièvement pour rassurer le client
- quand tout est clair, fais un récapitulatif simple et humain
- demande confirmation avant de créer la commande

 Après confirmation de commande :
- annonce la commande avec enthousiasme naturel
- donne le numéro de commande
- remercie sincèrement le client
- termine poliment la conversation
- ne pose plus de questions

Important :
Tu es professionnelle mais humaine.
Tu parles comme si tu étais au téléphone avec le client.
Jamais de ton administratif ou technique.
""",
        )

        #  Création d’un thread (mémoire persistante)
        thread = AgentThread()

        print("🟢 Chat démarré. Tape 'exit' pour quitter.\n")

        while True:
            user_msg = input("Client > ").strip()
            if user_msg.lower() in {"q", "quit"}:
                break

            reply = await agent.run(
                messages=user_msg,
                tools=mcp_tools,
                thread=thread  #  mémoire activée ici
            )

            print(f"\nAgent > {reply}\n")

        await asyncio.sleep(0.1) # Pour laisser les tâches async internes (Cosmos, HTTP, MCP) se terminer proprement avant la fermeture de l'event loop.
       # Évite les erreurs "Session.request unexpected argument" au shutdown.



if __name__ == "__main__":
    asyncio.run(main())
