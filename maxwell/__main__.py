import argparse

import uvicorn

parser = argparse.ArgumentParser(description="Maxwell's Hoard")
parser.add_argument("--port", type=int, default=5243)
args = parser.parse_args()
uvicorn.run("maxwell.app:app", host="127.0.0.1", port=args.port)
