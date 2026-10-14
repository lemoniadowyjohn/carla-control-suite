import pathlib

root = pathlib.Path(r"G:\CARLA\carla_source_probe\Build")
path = root / "CMakeLists.txt.in"

content = """# Automatically generated
set(CARLA_VERSION 0.9.16)

set(CMAKE_CXX_STANDARD 14)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

add_definitions(-D_WIN32_WINNT=0x0600)
add_definitions(-DHAVE_SNPRINTF)
STRING (REGEX REPLACE "/RTC(su|[1su])" "" CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS}")

add_definitions(-DBOOST_ERROR_CODE_HEADER_ONLY)
add_definitions(-DLIBCARLA_IMAGE_WITH_PNG_SUPPORT)

set(BOOST_INCLUDE_PATH "G:/CARLA/carla_source_probe/Build/boost-1.84.0-install/include")
set(BOOST_LIB_PATH "G:/CARLA/carla_source_probe/Build/boost-1.84.0-install/lib")

set(RPCLIB_INCLUDE_PATH "G:/CARLA/carla_source_probe/Build/rpclib-install/include")
set(RPCLIB_LIB_PATH "G:/CARLA/carla_source_probe/Build/rpclib-install/lib")

if (CMAKE_BUILD_TYPE STREQUAL "Server")
  add_definitions(-DBOOST_TYPE_INDEX_FORCE_NO_RTTI_COMPATIBILITY)
  add_compile_options(/EHsc)
  add_definitions(-DASIO_NO_EXCEPTIONS)
  add_definitions(-DBOOST_NO_EXCEPTIONS)
  add_definitions(-DLIBCARLA_NO_EXCEPTIONS)
  add_definitions(-DPUGIXML_NO_EXCEPTIONS)
  set(GTEST_INCLUDE_PATH "G:/CARLA/carla_source_probe/Build/gtest-install/include")
  set(GTEST_LIB_PATH "G:/CARLA/carla_source_probe/Build/gtest-install/lib")
elseif (CMAKE_BUILD_TYPE STREQUAL "Client")
  set(ZLIB_INCLUDE_PATH "G:/CARLA/carla_source_probe/Build/zlib-install/include")
  set(ZLIB_LIB_PATH "G:/CARLA/carla_source_probe/Build/zlib-install/lib")
  set(LIBPNG_INCLUDE_PATH "G:/CARLA/carla_source_probe/Build/libpng-1.2.37-install/include")
  set(LIBPNG_LIB_PATH "G:/CARLA/carla_source_probe/Build/libpng-1.2.37-install/lib")
  set(RECAST_INCLUDE_PATH "G:/CARLA/carla_source_probe/Build/recast-install/include")
  set(RECAST_LIB_PATH "G:/CARLA/carla_source_probe/Build/recast-install/lib")
endif ()
"""

path.write_text(content, encoding="utf-8")
print("Created CMakeLists.txt.in")
