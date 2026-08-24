"""
Command-Line Interface (CLI) for Aster & Row RAG Support Agent.
Supports interactive multi-turn conversations and single query processing
with optional --json structured output mode.
"""

import argparse
import json
import sys
from src.agent import AsterRowSupportAgent


def main():
    parser = argparse.ArgumentParser(description="Aster & Row AI Support Agent CLI")
    parser.add_argument("--query", type=str, help="Single query to process")
    parser.add_argument("--session", type=str, default="cli_session", help="Session identifier for state persistence")
    parser.add_argument("--json", action="store_true", help="Output machine-parseable JSON response")
    args = parser.parse_args()

    agent = AsterRowSupportAgent()

    if args.query:
        response = agent.process_message(args.query, session_id=args.session)
        if args.json:
            out_data = {
                "text": response.text,
                "sources": response.sources,
                "status": response.status.value,
                "handoff_reason": response.handoff_reason.value if response.handoff_reason else None,
                "tool_calls": response.tool_calls
            }
            print(json.dumps(out_data, indent=2))
        else:
            print("\n=======================================================")
            print(f"QUERY    : {args.query}")
            print(f"STATUS   : {response.status.value}")
            print(f"SOURCES  : {response.sources}")
            if response.handoff_reason:
                print(f"HANDOFF  : {response.handoff_reason.value}")
            print("-------------------------------------------------------")
            print(f"RESPONSE :\n{response.text}")
            print("=======================================================\n")
        return

    print("=======================================================")
    print("Aster & Row Support Agent Interactive CLI Interface")
    print("Type 'exit' or 'quit' to end session.")
    print("=======================================================\n")

    session_id = args.session
    while True:
        try:
            user_input = input("Customer: ").strip()
            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit"):
                print("\nEnding session. Goodbye!")
                break

            response = agent.process_message(user_input, session_id=session_id)
            if args.json:
                out_data = {
                    "text": response.text,
                    "sources": response.sources,
                    "status": response.status.value,
                    "handoff_reason": response.handoff_reason.value if response.handoff_reason else None,
                    "tool_calls": response.tool_calls
                }
                print(json.dumps(out_data, indent=2))
            else:
                print(f"\nAgent [{response.status.value}]: {response.text}")
                if response.sources:
                    print(f"Citations: {response.sources}")
                print()
        except (KeyboardInterrupt, EOFError):
            print("\nSession interrupted. Exiting.")
            break


if __name__ == "__main__":
    main()
