FROM docker.io/ros:jazzy@sha256:be7350a0efd17925415a6a3a076d6009b425af7500b0a5cdb5d717e87ef46f39

SHELL ["/bin/bash", "-c"]

RUN apt-get update && \
    apt-get install -y \
    dos2unix \
    python3-numpy \
    ros-jazzy-rmw-cyclonedds-cpp && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY src/realistic_targeting src/realistic_targeting/
RUN source /opt/ros/jazzy/setup.bash && \
    colcon build --symlink-install --packages-select realistic_targeting

COPY config/cyclonedds.xml /config/
ENV CYCLONEDDS_URI=file:///config/cyclonedds.xml

COPY src/realistic_targeting/ros_entrypoint.sh .
RUN dos2unix ros_entrypoint.sh && chmod +x ros_entrypoint.sh

ENTRYPOINT ["./ros_entrypoint.sh"]
