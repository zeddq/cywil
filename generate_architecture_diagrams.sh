#!/bin/bash

# Script to generate architecture diagrams from DOT files

echo "Generating AI Paralegal POC Architecture Diagrams..."

# Check if graphviz is installed
if ! command -v dot &> /dev/null; then
    echo "Error: Graphviz is not installed. Please install it first:"
    echo "  macOS: brew install graphviz"
    echo "  Ubuntu/Debian: sudo apt-get install graphviz"
    echo "  RHEL/CentOS: sudo yum install graphviz"
    exit 1
fi

# Generate module-level architecture diagram
echo "1. Generating module-level architecture diagram..."
dot -Tpng codebase_architecture.dot -o codebase_architecture.png
dot -Tsvg codebase_architecture.dot -o codebase_architecture.svg
echo "   Created: codebase_architecture.png and codebase_architecture.svg"

# Generate detailed architecture diagram
echo "2. Generating detailed architecture diagram..."
dot -Tpng codebase_architecture_detailed.dot -o codebase_architecture_detailed.png
dot -Tsvg codebase_architecture_detailed.dot -o codebase_architecture_detailed.svg
echo "   Created: codebase_architecture_detailed.png and codebase_architecture_detailed.svg"

echo ""
echo "Architecture diagrams generated successfully!"
echo "You can view them with:"
echo "  open codebase_architecture.png"
echo "  open codebase_architecture_detailed.png"
echo ""
echo "SVG versions are also available for better quality and scalability."
