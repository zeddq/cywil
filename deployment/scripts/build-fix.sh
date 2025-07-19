#\!/bin/bash
cd "$(dirname "$0")/../.."
cp requirements-short.txt requirements.txt
./deployment/scripts/build-and-deploy.sh "$@"
