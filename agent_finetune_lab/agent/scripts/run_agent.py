import asyncio, argparse
from agent.config import Settings
from agent.core import Agent

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True)
    args = ap.parse_args()
    out = asyncio.run(Agent(Settings()).run(args.task))
    print(out)

if __name__ == "__main__":
    main()
