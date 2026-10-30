cmake_minimum_required(VERSION 3.28.0...3.28.0 FATAL_ERROR)

project(SlicerVEScan)

#-----------------------------------------------------------------------------
# Extension meta-information
set(EXTENSION_HOMEPAGE "https://github.com/edoardoedr/SlicerVEScan")
set(EXTENSION_CONTRIBUTORS "Edoardo De Rose (KIT, IBT)")
set(EXTENSION_DESCRIPTION "Lung vessel centerline trees, anatomical branch labels and crossing vessels (VE-SCAN)")
set(EXTENSION_ICONURL "https://raw.githubusercontent.com/edoardoedr/SlicerVEScan/main/SlicerVEScan.png")
set(EXTENSION_SCREENSHOTURLS "")
set(EXTENSION_DEPENDS "NA") # Specified as a list or "NA" if no dependencies

#-----------------------------------------------------------------------------
# Extension dependencies
find_package(Slicer REQUIRED)
include(${Slicer_USE_FILE})

#-----------------------------------------------------------------------------
# Extension modules
add_subdirectory(VEScan)
## NEXT_MODULE

#-----------------------------------------------------------------------------
include(${Slicer_EXTENSION_GENERATE_CONFIG})
include(${Slicer_EXTENSION_CPACK})
