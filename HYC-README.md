# HYC Aerospike Docker Image

# Prerequisites
Below python modules are required:

    etcd3
    gunicorn
    falcon
    requests
    google
    protobuf

These are already present src/requirements.txt

    pip install -r src/requirements.txt
# How to RUN
##### Building docker
    docker build . -t hyc-asd
    
##### Running docker
    docker run -it -d -p <doceker host port>:8000 --security-opt="seccomp=unconfined" --privileged=true --cap-add ALL --cap-add SYS_ADMIN -v /tmp:/var/log/aerospike/ -v /dev:/dev hyc-asd /run.sh --etcdip=<etcd ip> --svc_label=AS_Server --svc_idx=<Instance index> --mode=multicast --ip=<Multicast address to use for asd heartbeat> --port=<port for asd cluster heartbeat>

    docker run -it -d -p <doceker host port>:8000 --security-opt="seccomp=unconfined" --privileged=true --cap-add ALL --cap-add SYS_ADMIN -v /tmp:/var/log/aerospike/ -v /dev:/dev hyc-asd /run.sh --etcdip=<etcd ip> --svc_label=AS_Server --svc_idx=<Instance index> --mode=multicast --ip=<Comma seperated ips of all aerospike instances> --port=<port for asd cluster heartbeat>

When HA Manager issues component_start REST Api actual Aerospike server will be started.
