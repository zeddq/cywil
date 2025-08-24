# AI Paralegal POC - Architecture Diagrams

This directory contains architectural diagrams showing the module-level structure and dependencies of the AI Paralegal POC codebase.

## Available Diagrams

### 1. Module-Level Architecture (`codebase_architecture.dot`)
This diagram shows the high-level module structure of the codebase with the following components:

- **app** - Main application module
  - `app.core` - Core infrastructure (config, database, logging, LLM, tools)
  - `app.services` - Business logic services
  - `app.routes` - API endpoints
  - `app.repositories` - Data access layer
  - `app.paralegal_agents` - AI agent integration
  - `app.worker` - Background task processing (Celery)
  - `app.models` - Data models
  - `app.auth` - Authentication

- **ingest** - Data ingestion and processing
- **tests** - Test suites
- **deployment** - Deployment configurations
- **scripts** - Utility scripts
- **ui** - Frontend application

### 2. Detailed Architecture (`codebase_architecture_detailed.dot`)
This diagram provides a more detailed view showing:
- Key classes and their main methods
- Specific API endpoints
- Background task types
- External system integrations

## Generating the Diagrams

### Prerequisites
Install Graphviz on your system:
```bash
# macOS
brew install graphviz

# Ubuntu/Debian
sudo apt-get install graphviz

# RHEL/CentOS
sudo yum install graphviz
```

### Generate Diagrams
Run the provided script:
```bash
./generate_architecture_diagrams.sh
```

This will create PNG and SVG versions of both diagrams.

### Manual Generation
You can also generate specific formats manually:
```bash
# Generate PNG
dot -Tpng codebase_architecture.dot -o codebase_architecture.png

# Generate SVG (scalable, better quality)
dot -Tsvg codebase_architecture.dot -o codebase_architecture.svg

# Generate PDF
dot -Tpdf codebase_architecture.dot -o codebase_architecture.pdf
```

## Understanding the Diagrams

### Dependency Arrows
- **Solid arrows** - Direct dependencies
- **Dashed arrows** - Indirect or runtime dependencies
- **Dotted arrows** - Test dependencies

### Color Coding
- **Blue shades** - Core application components
- **Orange shades** - Data ingestion components
- **Green shades** - Infrastructure and tools
- **Gray** - Test components
- **Yellow** - External systems

### Module Groupings
Modules are grouped in dashed boxes representing logical boundaries:
- Application modules are grouped together
- Infrastructure components are separate
- External dependencies are shown as cylinders (databases) or ellipses (APIs)

## Mermaid Diagram
A Mermaid version of the module architecture is also available in the codebase, which can be viewed directly in the chat interface or in any Mermaid-compatible viewer.

## Updating the Diagrams
When the codebase structure changes:
1. Update the relevant `.dot` files
2. Run `./generate_architecture_diagrams.sh` to regenerate images
3. Commit both the `.dot` files and generated images
