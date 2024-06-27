#!/bin/sh

set -e

# activate our virtual environment here
. /opt/.venv/bin/activate

# Evaluating passed command:
exec "$@"
