#!/bin/bash
# Wrapper script for jj to bypass shell integration issues

# Run jj with a clean environment
exec env -i \
    PATH="$PATH" \
    HOME="$HOME" \
    USER="$USER" \
    TERM="$TERM" \
    /opt/homebrew/bin/jj "$@"
