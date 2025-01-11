#!/usr/bin/env bash
# wait-for-it.sh: Wait for a service to be ready
# Source: https://github.com/vishnubob/wait-for-it

set -e

host="$1"
port="$2"
shift 2
cmd="$@"

while ! nc -z "$host" "$port"; do
  echo "Waiting for $host:$port to be ready..."
  sleep 2
done

echo "$host:$port is ready."
exec $cmd

