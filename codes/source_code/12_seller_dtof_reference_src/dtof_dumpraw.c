/*
 * Copyright (c) 2023 HiSilicon (Shanghai) Technologies CO., LIMITED.
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

#include <unistd.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <sys/ioctl.h>
#ifndef __HuaweiLite__
#include <poll.h>
#endif
#include <sys/mman.h>
#include <fcntl.h>
#include <errno.h>
#include <pthread.h>
#include <signal.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <sys/time.h>
#include <time.h>

#include "ot_common.h"
#include "ot_common_video.h"
#include "ot_common_sys.h"
#include "ot_common_vi.h"
#include "ot_common_isp.h"
#include "sample_comm.h"

#include "dtof/DataProc.h"
#include "dtof/gs1860_cmos.h"

#include "dtof_common.h"

#define MAX_FRM_CNT 25
#define SMIT_DEV_NO 0
#define HEIGHT 30
#define WEIGHT 40
#define BIN_NUM 64
#define MILLI_SEC 4000
#define SECOND_TO_MILLI_SECOND (1000 * 1000)
#define NANO_SECOND_TO_MILLI_SECOND 1000
#define MID_PIXEL (14 * 40 + 19)
#define VALID_DATA_NUM 3

#define CALIB_PARA_LEN 9
#define CLOUDPOINT_CALIB_PARA_LEN 12
#define UDP_DATA_PIXEL_NUMBER (30 * 40)

#define DTOF_INI_FILE_PATH   "./dtof.ini"
#define DTOF_SPOT_FILE_PATH  "./spot_coor.bin"

#pragma pack(1)
typedef struct stTofAdditionInfo {
    short width;
    short height;
    short frameRate;
    unsigned char  version;
    float reserved[CLOUDPOINT_CALIB_PARA_LEN];
} TofAdditionInfo;

typedef struct stTofUdpPacketHead {
    short checkSum;
    short seqNum;
    unsigned int startPixel;
    short pixelNumber;
    unsigned int timestampSeconds;
    unsigned int timestampNanoSeconds;
    TofAdditionInfo addtional;
} TofUdpPacketHead;

typedef struct stTofPixelContent {
    short depth;
    unsigned char  confidence;
    unsigned char  flag;
} TofPixelContent;

typedef struct stTofUdpPacketPixelData {
    TofPixelContent pixelData[UDP_DATA_PIXEL_NUMBER];
} TofUdpPacketData;

typedef struct stTofDataUdpPacket {
    TofUdpPacketHead head;
    TofUdpPacketData data;
} TofDataUdpPacket;
#pragma pack()

static volatile sig_atomic_t g_exit_flag;

static DtofHandleConfig* g_handle_config = NULL;
static DtofHandle* g_handle = NULL;
static pthread_t g_thread_pid;

extern td_s32 UdpSendInit(td_char* serverip);
extern td_s32 UdpSendTofData(td_u16 *distance, td_float *para);
extern td_void UdpSendDeinit();

static ot_wdr_mode sample_comm_vi_get_wdr_mode_by_sns_type(sample_sns_type sns_type)
{
    switch (sns_type) {
        case OV_OS08A20_MIPI_8M_30FPS_12BIT:
        case OV_OS04A10_MIPI_4M_30FPS_12BIT:
        case OV_OS08B10_MIPI_8M_30FPS_12BIT:
        case OV_OS05A10_SLAVE_MIPI_4M_30FPS_12BIT:
        case SONY_IMX347_SLAVE_MIPI_4M_30FPS_12BIT:
        case SONY_IMX347_2L_SLAVE_MIPI_2M_30FPS_12BIT:
        case SC450AI_MIPI_4M_30FPS_10BIT:
        case SC450AI_2L_MIPI_4M_30FPS_10BIT:
        case SC450AI_2L_MIPI_2M_30FPS_10BIT:
        case HISI_GS1860_MIPI_1M_30FPS_10BIT:
            return OT_WDR_MODE_NONE;

        case OV_OS08A20_MIPI_8M_30FPS_12BIT_WDR2TO1:
        case OV_OS08B10_MIPI_8M_30FPS_12BIT_WDR2TO1:
        case SC450AI_MIPI_4M_30FPS_10BIT_WDR2TO1:
            return OT_WDR_MODE_2To1_LINE;

        case SONY_IMX485_MIPI_8M_30FPS_10BIT_WDR3TO1:
            return OT_WDR_MODE_3To1_LINE;

        default:
            return OT_WDR_MODE_NONE;
    }
}

static td_s32 get_dump_pipe(ot_vi_pipe vi_pipe, ot_vi_bind_pipe *bind_pipe, td_s32 vi_dev)
{
    td_s32 ret;
    ot_vi_dev_attr dev_attr;

    (td_void)memset_s(bind_pipe, sizeof(ot_vi_bind_pipe), 0, sizeof(ot_vi_bind_pipe));

    ret = ss_mpi_vi_get_bind_by_dev(vi_dev, bind_pipe);
    if (ret != TD_SUCCESS) {
        printf("ss_mpi_vi_get_bind_by_dev error 0x%0x !\n", ret);
        return TD_FAILURE;
    }

    ret = ss_mpi_vi_get_dev_attr(vi_dev, &dev_attr);
    if (ret != TD_SUCCESS) {
        printf("get vi_dev %d attr failed!\n", vi_dev);
        return TD_FAILURE;
    }

    ot_wdr_mode wdr_mode = sample_comm_vi_get_wdr_mode_by_sns_type(HISI_GS1860_MIPI_1M_30FPS_10BIT);

    if ((wdr_mode == OT_WDR_MODE_NONE) || (wdr_mode == OT_WDR_MODE_BUILT_IN)) {
        bind_pipe->pipe_num = 1;
        bind_pipe->pipe_id[0] = vi_pipe;
    }

    return TD_SUCCESS;
}

static td_void bitwidth_to_pixelformat(td_u32 u32nbit, ot_pixel_format *pixel_format)
{
    if (u32nbit == 8) {
        *pixel_format = OT_PIXEL_FORMAT_RGB_BAYER_8BPP;
    } else if (u32nbit == 10) {
        *pixel_format = OT_PIXEL_FORMAT_RGB_BAYER_10BPP;
    } else if (u32nbit == 12) {
        *pixel_format = OT_PIXEL_FORMAT_RGB_BAYER_12BPP;
    } else if (u32nbit == 14) {
        *pixel_format = OT_PIXEL_FORMAT_RGB_BAYER_14BPP;
    } else if (u32nbit == 16) {
        *pixel_format = OT_PIXEL_FORMAT_RGB_BAYER_16BPP;
    } else {
        *pixel_format = OT_PIXEL_FORMAT_RGB_BAYER_16BPP;
    }
}

static td_s32 set_dump_pipe_attr(ot_vi_bind_pipe* bind_pipe, ot_vi_frame_dump_attr* backup_dump_attr, int dump_attr_len,
    ot_vi_pipe_attr* backup_pipe_attr, int pipe_attr_len)
{
    td_s32 ret = TD_SUCCESS;
    td_u32 u32nbit = 10;
    td_u32 u32rawdepth = 2;
    ot_pixel_format pixel_format;
    ot_vi_frame_dump_attr dump_attr;
    ot_vi_pipe_attr pipe_attr;

    bitwidth_to_pixelformat(u32nbit, &pixel_format);

    for (td_u32 i = 0; i < bind_pipe->pipe_num; i++) {
        ret = ss_mpi_vi_get_pipe_frame_dump_attr(bind_pipe->pipe_id[i], &backup_dump_attr[i]);
        if (ret != TD_SUCCESS) {
            printf("get vi_pipe %d dump attr failed!\n", bind_pipe->pipe_id[i]);
            return ret;
        }

        (td_void)memcpy_s(&dump_attr, sizeof(ot_vi_frame_dump_attr),
            &backup_dump_attr[i], sizeof(ot_vi_frame_dump_attr));
        dump_attr.enable = TD_TRUE;
        dump_attr.depth = u32rawdepth;

        ret = ss_mpi_vi_set_pipe_frame_dump_attr(bind_pipe->pipe_id[i], &dump_attr);
        if (ret != TD_SUCCESS) {
            printf("set vi_pipe %d dump attr failed!\n", bind_pipe->pipe_id[i]);
            return ret;
        }

        ret = ss_mpi_vi_get_pipe_attr(bind_pipe->pipe_id[i], &backup_pipe_attr[i]);
        if (ret != TD_SUCCESS) {
            printf("get vi_pipe %d attr failed!\n", bind_pipe->pipe_id[i]);
            return ret;
        }

        (td_void)memcpy_s(&pipe_attr, sizeof(ot_vi_pipe_attr), &backup_pipe_attr[i], sizeof(ot_vi_pipe_attr));
        pipe_attr.pixel_format = pixel_format;
        pipe_attr.compress_mode = OT_COMPRESS_MODE_NONE;

        ret = ss_mpi_vi_set_pipe_attr(bind_pipe->pipe_id[i], &pipe_attr);
        if (ret != TD_SUCCESS) {
            printf("set vi_pipe %d attr failed!\n", bind_pipe->pipe_id[i]);
            return ret;
        }
    }
    return ret;
}

static td_u16* deal_frame_data(ot_video_frame_info *frame_info)
{
    ot_video_frame* video_frame = &frame_info->video_frame;
    td_u32 u32tmpstride = 2 * video_frame->width;

    td_ulong size = u32tmpstride * (video_frame->height);
    td_ulong phy_addr = video_frame->phys_addr[0];

    td_u8 *virt_addr = (td_u8 *)ss_mpi_sys_mmap(phy_addr, size);
    if (virt_addr == TD_NULL) {
        return TD_NULL;
    }

    td_u8 *pu8data = virt_addr;

    td_u16 *pu16data = (td_u16*)malloc(2 * video_frame->width * video_frame->height); /* 2 * w * h */
    if (pu16data == TD_NULL) {
        fprintf(stderr, "alloc memory failed\n");
        ss_mpi_sys_munmap(virt_addr, size);
        virt_addr = TD_NULL;
        return TD_NULL;
    }

    td_s32 s32outcnt = 0;
    for (td_s32 u32h = 0; u32h < video_frame->height; u32h++) {
        /* 第一行是包头去掉，不是测量数据，暂时不记录 */
        if (u32h > 0) {
            for (td_s32 i = 0; i < video_frame->width / 4; i++) { /* 4 pixels consists of 5 bytes */
                /* byte4 byte3 byte2 byte1 byte0 */
                td_u8 *pu8tmp = pu8data + 5 * i; /* 5 byte step */
                td_ulong u64val = pu8tmp[0] + ((td_u32)pu8tmp[1] << 8) +
                        ((td_u32)pu8tmp[2] << 16) +
                        ((td_u32)pu8tmp[3] << 24) +
                        ((td_ulong)pu8tmp[4] << 32);

                pu16data[s32outcnt++] = u64val & 0x3ff;
                pu16data[s32outcnt++] = (u64val >> 10) & 0x3ff;
                pu16data[s32outcnt++] = (u64val >> 20) & 0x3ff;
                pu16data[s32outcnt++] = (u64val >> 30) & 0x3ff;
            }
        }
        pu8data += video_frame->stride[0];
    }

    ss_mpi_sys_munmap(virt_addr, size);
    virt_addr = NULL;

    return pu16data;
}

static void fill_to_data(TofDataUdpPacket* tofData, unsigned short* srcDepth)
{
    for (int i = 0; i < UDP_DATA_PIXEL_NUMBER; i++) {
        tofData->data.pixelData[i].depth = srcDepth[i];
    }
}

static int save_tof_data(FILE* fp, unsigned short *srcDepth, float para[CALIB_PARA_LEN])
{
    TofDataUdpPacket tofData;
    tofData.head.pixelNumber = 40 * 30;
    tofData.head.addtional.width = 40;
    tofData.head.addtional.height = 30;
    tofData.head.addtional.frameRate = 30;
    tofData.head.addtional.reserved[0] = para[0];
    tofData.head.addtional.reserved[1] = para[1];
    tofData.head.addtional.reserved[2] = para[2];
    tofData.head.addtional.reserved[3] = para[3];
    tofData.head.addtional.reserved[4] = para[4];
    tofData.head.addtional.reserved[5] = para[5];
    tofData.head.addtional.reserved[6] = para[6];
    tofData.head.addtional.reserved[7] = para[7];
    tofData.head.addtional.reserved[8] = para[8];
    tofData.head.addtional.reserved[9] = 0;
    tofData.head.addtional.reserved[10] = 0;
    tofData.head.addtional.reserved[11] = 0;

    (void)memset_s(&tofData.data.pixelData, sizeof(tofData.data.pixelData), 0, sizeof(tofData.data.pixelData));
    fill_to_data(&tofData, srcDepth);

    fwrite(&tofData, sizeof(tofData), 1, fp);
    fflush(fp);
    return TD_SUCCESS;
}

static int save_tof_dat(FILE* fp, td_u64 *file_size, td_u64 *frame_cnt)
{
    TofDataUdpPacket tofData;
    td_char buffer[256] = {0};
    struct timeval tv;
    struct tm* tm_info;
    td_u32 len = 0;

    gettimeofday(&tv, NULL);
    tm_info = localtime(&tv.tv_sec);
    strftime(buffer, sizeof(buffer), "%Y-%m-%d %H:%M:%S", tm_info);
    snprintf(buffer + strlen(buffer), sizeof(buffer) - strlen(buffer), ".%03ld", tv.tv_usec / 1000);

    len = sizeof(tofData);

    (*frame_cnt)++;
    fprintf(fp, "idx:%llu time:%-25s size:%-7u offset:%llu\n", *frame_cnt, buffer, len, *file_size);
    fflush(fp);
    *file_size += len;
    return TD_SUCCESS;
}

static td_void *dump_process(td_void *p)
{
    ot_vi_pipe vi_pipe = *(ot_vi_pipe*)p;
    ot_video_frame_info astFrame = {0};
    struct timespec temptv1 = {0};
    struct timespec temptv2 = {0};
    td_u16 switch_flag = 0;
    DtofHandle* handle = g_handle;
    unsigned int count = 0;

#ifdef SAVE_DTOF_DATA
    unsigned long long frame_cnt = 0;
    unsigned long long file_size = 0;

    time_t timestamp = time(NULL);
    td_char tmpbuf[128] = {0};
    struct tm* newtime=localtime(&timestamp);
    strftime(tmpbuf, 128, "%Y%m%d%H%M%S", newtime);

    td_char data_filename[256] = {0};
    td_char dat_filename[256] = {0};

    snprintf_s(data_filename, sizeof(data_filename), sizeof(data_filename) - 1,
        "TOF_chn%d_%s%s", vi_pipe, tmpbuf, ".raw");

    snprintf_s(dat_filename, sizeof(dat_filename), sizeof(dat_filename) - 1,
        "TOF_chn%d_%s%s", vi_pipe, tmpbuf, ".dat");

    FILE *data_fp = fopen(data_filename, "w");
    if(data_fp == NULL) {
        return TD_NULL;
    }

    FILE *dat_fp = fopen(dat_filename, "w");
    if(dat_fp == NULL) {
        return TD_NULL;
    }
#endif

    while (g_exit_flag == 0) {
        if (ss_mpi_vi_get_pipe_frame(vi_pipe, &astFrame, MILLI_SEC) != TD_SUCCESS) {
            printf("Linear:get vi_pipe %d frame err!\n", vi_pipe);
            continue;
        }

        handle->data = deal_frame_data(&astFrame);
        //handle->data = malloc(2560*31*2);
        ss_mpi_vi_release_pipe_frame(vi_pipe, &astFrame);
        if (handle->data == NULL) {
            return TD_NULL;
        }

        handle->dataLen = HEIGHT * WEIGHT * BIN_NUM;
        if (count < 30) { // 每30帧采集一次温度
            ++count;
        } else {
            handle->temperature = gs1860_tsensor_temperature(vi_pipe);
            count = 0;
        }

        // 切配置后前三帧数据丢弃
        if (switch_flag != 0) {
            free(handle->data);
            handle->data = NULL;
            switch_flag--;
            continue;
        }

        clock_gettime(CLOCK_MONOTONIC, &temptv2);
        long duration = temptv2.tv_sec * SECOND_TO_MILLI_SECOND + temptv2.tv_nsec / NANO_SECOND_TO_MILLI_SECOND -
            (temptv1.tv_sec * SECOND_TO_MILLI_SECOND + temptv1.tv_nsec / NANO_SECOND_TO_MILLI_SECOND);
        // printf("---------[dtofPrcess]: %ld us\n", duration);
        clock_gettime(CLOCK_MONOTONIC, &temptv1);

        DtofProcess(handle);

        // printf("distance[14][19] = %d\n", handle->dtofOutput.distance[MID_PIXEL]);
        free(handle->data);
        handle->data = NULL;
        UdpSendTofData(handle->dtofOutput.distance, handle->dtofOutput.para);

#ifdef SAVE_DTOF_DATA
        save_tof_data(data_fp, handle->dtofOutput.distance, handle->dtofOutput.para);
        save_tof_dat(dat_fp, &file_size, &frame_cnt);
#endif
        // 动态切配置
        if (handle->dtofOutput.switchFlag == 1 && handle->dtofOutput.configFlag == 0) {
            printf("------switch to 1000ps-------\n");
            gs1860_1000ps_config(vi_pipe);
            handle->dtofOutput.switchFlag = 0;
            switch_flag = VALID_DATA_NUM;
        } else if (handle->dtofOutput.switchFlag == 1 && handle->dtofOutput.configFlag == 1) {
            printf("------switch to 500ps------\n");
            gs1860_500ps_config(vi_pipe);
            handle->dtofOutput.switchFlag = 0;
            switch_flag = VALID_DATA_NUM;
        }
    }

#ifdef SAVE_DTOF_DATA
    fclose(data_fp);
    data_fp = NULL;

    fclose(dat_fp);
    dat_fp = NULL;
#endif

    return TD_NULL;
}

td_s32 vi_bayerdump(ot_vi_pipe vi_pipe, td_s32 vi_dev)
{
    ot_vi_bind_pipe bind_pipe;
    ot_vi_frame_dump_attr backup_dump_attr[OT_VI_MAX_PIPE_NUM];
    ot_vi_pipe_attr backup_pipe_attr[OT_VI_MAX_PIPE_NUM];

    printf("\nNOTICE: vi_bayerdump be used for TESTING !!!\n");

    td_s32 ret = get_dump_pipe(vi_pipe, &bind_pipe, vi_dev);
    if (ret != TD_SUCCESS) {
        printf("get_dump_pipe failed 0x%d!\n", ret);
        return OT_ERR_VI_ILLEGAL_PARAM;
    }

    ret = set_dump_pipe_attr(&bind_pipe, backup_dump_attr, OT_VI_MAX_PIPE_NUM, backup_pipe_attr, OT_VI_MAX_PIPE_NUM);
    if (ret != TD_SUCCESS) {
        printf("get_dump_pipe failed 0x%d!\n", ret);
        return OT_ERR_VI_ILLEGAL_PARAM;
    }

    if (bind_pipe.pipe_num == 1) {
        g_exit_flag = 0;
        ret = pthread_create(&g_thread_pid, 0, dump_process, (td_void*)&vi_pipe);
        if (ret != TD_SUCCESS) {
            printf("dump linear bayer failed\n");
            return ret;
        }
    }

    return ret;
}

td_s32 dtof_init(ot_vi_pipe vi_pipe, td_char* serverip)
{
    g_handle_config = (DtofHandleConfig*)malloc(sizeof(DtofHandleConfig));
    if (g_handle_config == TD_NULL) {
        return TD_FAILURE;
    }
    memset_s(g_handle_config, sizeof(DtofHandleConfig), 0, sizeof(DtofHandleConfig));

    g_handle_config->iniFile  = DTOF_INI_FILE_PATH;
    g_handle_config->spotFile = DTOF_SPOT_FILE_PATH;

    gs1860_read_eeprom(vi_pipe, (unsigned char*)&(g_handle_config->dtofCalibPara), sizeof(g_handle_config->dtofCalibPara));

    g_handle = DtofInit(g_handle_config);
    if (g_handle == TD_NULL) {
        free(g_handle_config);
        return TD_FAILURE;
    }

    // 相机标定参数：内参(fx,fy,cx,cy)，畸变参数(k1,k2,p1,p2,k3)
    printf("fx:%.05d, fy:%.05d, cx:%.05d, cy:%.05d, k1:%.05d, k2:%.05d, p1:%.05d, p2:%.05d, k3:%.05d\n",
        g_handle_config->dtofCalibPara[0], g_handle_config->dtofCalibPara[1],
        g_handle_config->dtofCalibPara[2], g_handle_config->dtofCalibPara[3],
        g_handle_config->dtofCalibPara[4], g_handle_config->dtofCalibPara[5],
        g_handle_config->dtofCalibPara[6], g_handle_config->dtofCalibPara[7],
        g_handle_config->dtofCalibPara[8]);

    UdpSendInit(serverip);

    return TD_SUCCESS;
}

td_void dtof_deinit(td_void)
{
    g_exit_flag = 1;
    pthread_join(g_thread_pid, NULL);

    UdpSendDeinit();

    if (g_handle->data != NULL) {
        free(g_handle->data);
        g_handle->data = NULL;
    }
    if (g_handle != NULL) {
        DtofDestory(g_handle);
        g_handle = NULL;
    }
    if (g_handle_config != NULL) {
        free(g_handle_config);
        g_handle_config = NULL;
    }
}

