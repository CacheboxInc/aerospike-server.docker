#!/bin/sh

if [ -z ${7} ]
	then
	gunicorn -b 0.0.0.0:8000 hyc_asd_mgr:app etcdip=$1 svc_label=$2 svc_idx=$3 mode=$4 ip=$5 port=$6
else
	gunicorn -b 0.0.0.0:$7 hyc_asd_mgr:app etcdip=$1 svc_label=$2 svc_idx=$3 mode=$4 ip=$5 port=$6
fi
