cmake_minimum_required(VERSION 3.8)
project(realistic_targeting)

find_package(ament_cmake REQUIRED)
find_package(ament_cmake_python REQUIRED)
find_package(rosidl_default_generators REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "srv/RunRealisticTargeting.srv"
)

ament_python_install_package(realistic_targeting_py)

install(PROGRAMS
  scripts/realistic_targeting_node
  DESTINATION lib/${PROJECT_NAME}
)

install(
  DIRECTORY launch
  DESTINATION share/${PROJECT_NAME}
)

ament_export_dependencies(rosidl_default_runtime)
ament_package()
