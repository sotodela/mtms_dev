from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription(
        [
            Node(
                package="realistic_targeting",
                executable="realistic_targeting_node",
                name="realistic_targeting",
                output="screen",
            ),
        ]
    )
