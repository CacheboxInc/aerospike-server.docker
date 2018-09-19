#!/bin/sh

gunicorn -b 0.0.0.0:8000 hyc_asd_mgr:app $1 $2 $3 $4 $5
