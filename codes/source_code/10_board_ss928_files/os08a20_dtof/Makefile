# Place this directory under SS928V100_SDK_V2.0.2.2_MPP_Sample-master/src/os08a20_dtof/
# Build: cd <sdk>/src/os08a20_dtof && make OS_TYPE=openeuler

include ../Makefile.param

SENSOR0_TYPE := OV_OS08A20_MIPI_8M_30FPS_12BIT
SENSOR1_TYPE := HISI_GS1860_MIPI_1M_30FPS_10BIT
SENSOR2_TYPE := HISI_GS1860_MIPI_1M_30FPS_10BIT

########### SRCS & INC ############
INC_FLAGS += $(INCLUDES)
INC_FLAGS += -I$(COMMON_DIR)
INC_FLAGS += -I./scene_auto/include
INC_FLAGS += -I./scene_auto/src/sample/
INC_FLAGS += -I./scene_auto/tools/configaccess/include
INC_FLAGS += -I./scene_auto/tools/iniparser/include
INC_FLAGS += -I./dtof/include

SMP_SRCS := $(filter-out $(PWD)/pwm.c,$(wildcard $(PWD)/*.c))
SMP_SRCS += $(wildcard $(PWD)/scene_auto/tools/configaccess/src/*.c)
SMP_SRCS += $(wildcard $(PWD)/scene_auto/tools/iniparser/src/*.c)
SMP_SRCS += $(wildcard $(PWD)/scene_auto/src/core/*.c)
SMP_SRCS += $(PWD)/scene_auto/src/sample/scene_loadparam.c

# dToF-specific static libs (pre-built for SS928, from open_camera vendor)
DTOF_LIBS := ./dtof/lib/libdepth_process.a
DTOF_LIBS += ./dtof/lib/libsns_gs1860.a

TARGET := sample_os08a20_dtof

CFLAGS += $(EXTRA_CFLAGS)

TARGET_PATH := $(PWD)

OBJS := $(SMP_SRCS:%.c=%.o)

.PHONY: clean all

all: $(TARGET)

$(TARGET): $(COMM_OBJ) $(OBJS)
	$(CC) $(CFLAGS) $(INC_FLAGS) -lpthread -lm -o $(TARGET_PATH)/$@ $^ \
		-Wl,--start-group $(MPI_LIBS) $(DTOF_LIBS) $(AUDIO_LIBS) -Wl,--end-group

%.o: %.c
	$(CC) $(CFLAGS) $(INC_FLAGS) -c $< -o $@

clean:
	@rm -f $(TARGET_PATH)/$(TARGET)
	@rm -f $(OBJS)
	@rm -f $(COMM_OBJ)
