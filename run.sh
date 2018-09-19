#!/bin/sh

echo "ASD package run"
/start.sh $1 $2 $3 $4 $5
tail -f /dev/null
