#!/bin/bash
# Script to run main.js and write output to output.txt
# Checks if main.js exists, then executes it with Node.js

if [ ! -f "main.js" ]; then
  echo "Error: main.js not found in current directory!" >&2
  exit 1
fi

# Check if node is available
if ! command -v node &> /dev/null; then
  echo "Error: Node.js is not installed or not in PATH" >&2
  exit 1
fi

# Run main.js and redirect output to output.txt
node main.js > output.txt 2>&1

echo "Execution complete. Output written to output.txt"
