/*
  Copyright (c), 2001-2022, Shenshu Tech. Co., Ltd.
 */

#include <unistd.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <sys/ioctl.h>
#include <poll.h>
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

#include "dtof/DataProc.h"
#include "dtof/gs1860_cmos.h"

#include "dtof_common.h"
#include "dtof_pip.h"

static volatile sig_atomic_t g_exit_flag = {0};

static DtofHandleConfig* g_dtof_cfg[MAX_DTOF] = {NULL};
static DtofHandle* g_dtof_handle[MAX_DTOF] = {NULL};
static pthread_t g_thread_pid= {0};

typedef struct {
    ot_vi_pipe dtof_vi_pipe[MAX_DTOF];
    td_s32 dtof_cnt;
    ot_vpss_grp rgb_vpss_grp;
    ot_vpss_chn rgb_vpss_chn;
} dtof_thread_para;

static dtof_thread_para g_dtof_para;

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

static td_void *dump_process(td_void *arg)
{
    dtof_thread_para* para = (dtof_thread_para*)arg;
    td_s32 ret;
    struct timespec temptv1 = {0};
    struct timespec temptv2 = {0};
    td_s32 milli_sec = 20000;

    unsigned int count[MAX_DTOF] = {0};
    td_u16 switch_flag[MAX_DTOF] = {0};

    ot_video_frame_info dtof_video_frame[MAX_DTOF] = {0};
    ot_video_frame_info rgb_video_frame = {0};

    DtofHandle* dtof_handle[MAX_DTOF] = {0};
    dtof_ive_proc_info ive_proc_info[MAX_DTOF];
    for (int i = 0; i < para->dtof_cnt; i++) {
        dtof_handle[i] = g_dtof_handle[i];
        memset(&ive_proc_info[i], 0, sizeof(dtof_ive_proc_info));
        dtof_ive_proc_init(&ive_proc_info[i], PAD_WIDTH, PAD_HEIGHT);
    }

    while (g_exit_flag == 0) {

        ret = ss_mpi_vpss_get_chn_frame(para->rgb_vpss_grp, para->rgb_vpss_chn, &rgb_video_frame, milli_sec);
        if (ret != TD_SUCCESS) {
            printf("ss_mpi_vpss_get_chn_frame err!\n");
            continue;
        }

        for (int i = 0; i < para->dtof_cnt; i++) {
            if (ss_mpi_vi_get_pipe_frame(para->dtof_vi_pipe[i], &dtof_video_frame[i], milli_sec) != TD_SUCCESS) {
                printf("Linear:get vi_pipe %d frame err!\n", para->dtof_vi_pipe[i]);
                continue;
            }

            dtof_handle[i]->data = deal_frame_data(&dtof_video_frame[i]);
            ss_mpi_vi_release_pipe_frame(para->dtof_vi_pipe[i], &dtof_video_frame[i]);
            if (dtof_handle[i]->data == NULL) {
                continue;
            }

            dtof_handle[i]->dataLen = HEIGHT * WIDTH * BIN_NUM;

            if (count[i] < 30) { // 每30帧采集一次温度
                ++count[i];
            } else {
                dtof_handle[i]->temperature = gs1860_tsensor_temperature(para->dtof_vi_pipe[i]);
                count[i] = 0;
            }

            // 切配置后前三帧数据丢弃
            if (switch_flag[i] != 0) {
                free(dtof_handle[i]->data);
                dtof_handle[i]->data = NULL;
                switch_flag[i]--;
            } else {

                clock_gettime(CLOCK_MONOTONIC, &temptv2);
                long duration = temptv2.tv_sec * SECOND_TO_MILLI_SECOND + temptv2.tv_nsec / NANO_SECOND_TO_MILLI_SECOND -
                                (temptv1.tv_sec * SECOND_TO_MILLI_SECOND + temptv1.tv_nsec / NANO_SECOND_TO_MILLI_SECOND);
                // printf("---------[dtofPrcess]: %ld us\n", duration);
                clock_gettime(CLOCK_MONOTONIC, &temptv1);

                DtofProcess(dtof_handle[i]);

                // printf("dtof[%d]: distance[14][19] = %d\n", i, dtof_handle[i]->dtofOutput.distance[MID_PIXEL]);

                free(dtof_handle[i]->data);
                dtof_handle[i]->data = NULL;

                // IVE 深度伪彩
                dtof_convert_depth_to_colormap(dtof_handle[i], &ive_proc_info[i]);
            }

            dtof_overlay_colormap_to_frame(&ive_proc_info[i], &rgb_video_frame, i);

            // 动态切配置
            if (dtof_handle[i]->dtofOutput.switchFlag == 1 && dtof_handle[i]->dtofOutput.configFlag == 0) {
                printf("------switch dtof %d to 1000ps-------\n", i);
                gs1860_1000ps_config(para->dtof_vi_pipe[i]);
                dtof_handle[i]->dtofOutput.switchFlag = 0;
                switch_flag[i] = VALID_DATA_NUM;
            } else if (dtof_handle[i]->dtofOutput.switchFlag == 1 && dtof_handle[i]->dtofOutput.configFlag == 1) {
                printf("------switch dtof %d to 500ps------\n", i);
                gs1860_500ps_config(para->dtof_vi_pipe[i]);
                dtof_handle[i]->dtofOutput.switchFlag = 0;
                switch_flag[i] = VALID_DATA_NUM;
            }
        }

        ret = ss_mpi_vo_send_frame(para->rgb_vpss_grp, para->rgb_vpss_chn, &rgb_video_frame, milli_sec);
        if (ret != TD_SUCCESS) {
            printf("ss_mpi_vo_send_frame failed, ret:0x%x\n", ret);
        }

        ret = ss_mpi_vpss_release_chn_frame(para->rgb_vpss_grp, para->rgb_vpss_chn, &rgb_video_frame);
        if (ret != TD_SUCCESS) {
            printf("ss_mpi_vpss_release_chn_frame failed, ret:0x%x\n", ret);
        }
    }

    for (int i = 0; i < para->dtof_cnt; i++) {
        dtof_ive_proc_uninit(&ive_proc_info[i]);
    }

    return TD_NULL;
}

td_s32 vi_bayerdump_pip(ot_vi_pipe vi_pipe[],  ot_vi_dev vi_dev[], td_s32 cnt,
    ot_vpss_grp vpss_grp, ot_vpss_chn vpss_chn)
{
    td_s32 ret;
    ot_vi_bind_pipe bind_pipe;
    ot_vi_frame_dump_attr backup_dump_attr[OT_VI_MAX_PIPE_NUM];
    ot_vi_pipe_attr backup_pipe_attr[OT_VI_MAX_PIPE_NUM];

    printf("\nNOTICE: vi_bayerdump be used for TESTING !!!\n");

    for (int i = 0; i < cnt; i++) {
        ret = get_dump_pipe(vi_pipe[i], &bind_pipe, vi_dev[i]);
        if (ret != TD_SUCCESS) {
            printf("get_dump_pipe failed 0x%d!\n", ret);
            return OT_ERR_VI_ILLEGAL_PARAM;
        }

        ret = set_dump_pipe_attr(&bind_pipe, backup_dump_attr, OT_VI_MAX_PIPE_NUM, backup_pipe_attr, OT_VI_MAX_PIPE_NUM);
        if (ret != TD_SUCCESS) {
            printf("get_dump_pipe failed 0x%d!\n", ret);
            return OT_ERR_VI_ILLEGAL_PARAM;
        }

        g_dtof_para.dtof_vi_pipe[i] = vi_pipe[i];
    }

    g_dtof_para.dtof_cnt = cnt;
    g_dtof_para.rgb_vpss_grp = vpss_grp;
    g_dtof_para.rgb_vpss_chn = vpss_chn;

    g_exit_flag = 0;
    ret = pthread_create(&g_thread_pid, 0, dump_process, &g_dtof_para);
    if (ret != TD_SUCCESS) {
        printf("dump linear bayer failed\n");
        return ret;
    }

    return ret;
}

td_s32 dtof_pip_init(ot_vi_pipe vi_pipe[], td_s32 cnt)
{
    td_s32 i;

    if (cnt <= 0 || cnt > MAX_DTOF) {
        printf("invalid dtof count: %d\n", cnt);
        return TD_FAILURE;
    }

    for (i = 0; (i < cnt) && (i < MAX_DTOF); i++) {
        g_dtof_cfg[i] = (DtofHandleConfig*)malloc(sizeof(DtofHandleConfig));
        if (g_dtof_cfg[i] == TD_NULL) {
            return TD_FAILURE;
        }
        memset_s(g_dtof_cfg[i], sizeof(DtofHandleConfig), 0, sizeof(DtofHandleConfig));

        g_dtof_cfg[i]->iniFile  = DTOF_INI_FILE_PATH;
        g_dtof_cfg[i]->spotFile = DTOF_SPOT_FILE_PATH;

        gs1860_read_eeprom(vi_pipe[i], (unsigned char*)&(g_dtof_cfg[i]->dtofCalibPara), sizeof(g_dtof_cfg[i]->dtofCalibPara));

        g_dtof_handle[i] = DtofInit(g_dtof_cfg[i]);
        if (g_dtof_handle[i] == TD_NULL) {
            free(g_dtof_cfg[i]);
            return TD_FAILURE;
        }

        // 相机标定参数：内参(fx,fy,cx,cy)，畸变参数(k1,k2,p1,p2,k3)
        printf("fx:%.05d, fy:%.05d, cx:%.05d, cy:%.05d, k1:%.05d, k2:%.05d, p1:%.05d, p2:%.05d, k3:%.05d\n",
            g_dtof_cfg[i]->dtofCalibPara[0], g_dtof_cfg[i]->dtofCalibPara[1],
            g_dtof_cfg[i]->dtofCalibPara[2], g_dtof_cfg[i]->dtofCalibPara[3],
            g_dtof_cfg[i]->dtofCalibPara[4], g_dtof_cfg[i]->dtofCalibPara[5],
            g_dtof_cfg[i]->dtofCalibPara[6], g_dtof_cfg[i]->dtofCalibPara[7],
            g_dtof_cfg[i]->dtofCalibPara[8]);
    }
    return TD_SUCCESS;
}

td_void dtof_pip_deinit(td_s32 cnt)
{
    if (cnt <= 0 || cnt > MAX_DTOF) {
        printf("invalid dtof count: %d\n", cnt);
        return TD_FAILURE;
    }

    g_exit_flag = 1;

    if (g_thread_pid) {
        pthread_join(g_thread_pid, NULL);
        g_thread_pid = 0;
    }

    for (int i = 0; (i < cnt) && (i < MAX_DTOF); i++) {
        if (g_dtof_handle[i]) {
            if (g_dtof_handle[i]->data) {
                free(g_dtof_handle[i]->data);
                g_dtof_handle[i]->data = NULL;
            }
            DtofDestory(g_dtof_handle[i]);
            g_dtof_handle[i] = NULL;
        }
        if (g_dtof_cfg[i]) {
            free(g_dtof_cfg[i]);
            g_dtof_cfg[i] = NULL;
        }
    }
}

