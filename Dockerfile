#
# Aerospike Server Dockerfile
#
# http://github.com/aerospike/aerospike-server.docker
#


FROM debian:stretch-slim

ENV AEROSPIKE_VERSION 4.7.0.5
ENV AEROSPIKE_SHA256 6d16d914823c4b55b5b8ce61c5056be45cf366b8502d12fcb54c48882db502c2

# Install Aerospike Server and Tools

RUN \
  apt-get update -y \
  && apt-get install -y wget python lua5.2 gettext-base python-argparse python-bcrypt python-openssl logrotate net-tools iproute2 iputils-ping gettext-base\
  && wget "https://www.aerospike.com/artifacts/aerospike-server-community/${AEROSPIKE_VERSION}/aerospike-server-community-${AEROSPIKE_VERSION}-debian9.tgz" -O aerospike-server.tgz \
  && echo "$AEROSPIKE_SHA256 *aerospike-server.tgz" | sha256sum -c - \
  && mkdir aerospike \
  && tar xzf aerospike-server.tgz --strip-components=1 -C aerospike \
  && dpkg -i aerospike/aerospike-server-*.deb \
  && dpkg -i aerospike/aerospike-tools-*.deb \
  && mkdir -p /var/log/aerospike/ \
  && mkdir -p /var/run/aerospike/ \
  #&& rm -rf aerospike-server.tgz aerospike /var/lib/apt/lists/* \
  && rm -rf /opt/aerospike/lib/java \
  && dpkg -r wget ca-certificates \
  && dpkg --purge wget ca-certificates \
  && apt-get purge -y \
  && apt update;apt upgrade -y;apt autoremove -y

RUN apt-get update -y && apt-get install python-pip -y
RUN pip install --upgrade pip
COPY src/requirements.txt /requirements.txt
RUN pip install -r /requirements.txt

# Add the Aerospike configuration specific to this dockerfile
COPY entrypoint.sh /entrypoint.sh
COPY aerospike.template.conf /etc/aerospike/aerospike.conf
COPY aerospike_multicast.conf /etc/aerospike/aerospike_multicast.conf
COPY aerospike_mesh.conf /etc/aerospike/aerospike_mesh.conf
COPY aerospike.logrotate.txt /etc/logrotate.d/aerospike
COPY udf/* /etc/aerospike/
COPY start.sh /start.sh
COPY run.sh /run.sh


# Mount the Aerospike data directory
VOLUME ["/opt/aerospike/data"]
# VOLUME ["/etc/aerospike/"]


# Expose Aerospike ports
#
#   3000 – service port, for client connections
#   3001 – fabric port, for cluster communication
#   3002 – mesh port, for cluster heartbeat
#   3003 – info port
#
EXPOSE 3000 3001 3002 3003

RUN chmod +x /start.sh
RUN chmod +x /run.sh
ADD src /

# Execute the run script in foreground mode
CMD ["/run.sh"]
