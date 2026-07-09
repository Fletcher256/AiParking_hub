include ../Makefile.param

########### SRCS & INC ############
SMP_SRCS := $(wildcard $(PWD)/*.c)
SMP_SRCS += $(wildcard $(PWD)/pip/*.c)
SMP_SRCS += $(wildcard ../svp/common/sample_common_ive.c)

CFLAGS += -I$(PWD)/./
CFLAGS += -I$(PWD)/pip/
CFLAGS += -I$(PWD)/../svp/common/
#CFLAGS += -DSAVE_DTOF_DATA

MPI_LIBS += $(REL_LIB)/libss_ive.a
MPI_LIBS += $(3RDPARTY_LIBS_PATH)/libdepth_process.a

TARGET := sample_dtof

TARGET_PATH := $(PWD)

OBJS  := $(SMP_SRCS:%.c=%.o)

.PHONY : clean all

all: $(TARGET)

$(TARGET):$(COMM_OBJ) $(OBJS)
	$(CC) $(CFLAGS) -lpthread -lm -o $(TARGET_PATH)/$@ $^ -Wl,--start-group $(MPI_LIBS)  $(AUDIO_LIBS)  $(INIPARSER_LIB) -Wl,--end-group

clean:
	@rm -f $(TARGET_PATH)/$(TARGET)
	@rm -f $(OBJS)
	@rm -f $(COMM_OBJ)
