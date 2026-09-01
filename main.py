import os
from orchestrator import SelfExtendingOrchestrator

os.environ["OPENAI_API_KEY"] = "your-key-here"


def main():
    agent = SelfExtendingOrchestrator()

    tasks = [
        "What is the current USD to ILS exchange rate? Convert 5000 USD.",
        "Get the top 5 trending GitHub repositories today and list their names and stars.",
        "Generate a 16-character secure password and calculate its entropy in bits.",
    ]

    for task in tasks:
        result = agent.run(task)
        print(f"\n✅ Result: {result}\n")
        print("-" * 60)


if __name__ == "__main__":
    main()
