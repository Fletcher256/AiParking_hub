/*
  Copyright (c), 2001-2022, Shenshu Tech. Co., Ltd.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <pthread.h>
#include <signal.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <sys/ioctl.h>

#include "sample_comm.h"
#include "securec.h"
#include "rtsp_server_api.h"

#include "dtof/gs1860_cmos.h"

#define GS1860_REG_INI_FILE   "./gs1860_register.ini"

extern td_s32 dtof_init(ot_vi_pipe vi_pipe, td_char* serverip);
extern td_void dtof_deinit(td_void);
extern td_s32 vi_bayerdump(ot_vi_pipe vi_pipe, td_s32 vi_dev);
extern td_s32 sample_comm_request_idr(ot_venc_chn chn, td_bool instant);

static volatile sig_atomic_t g_sig_flag = 0;
static volatile td_bool g_camera_venc_started = TD_FALSE;
static td_bool g_camera_rtsp_rotate_180 = TD_FALSE;

#define check_digit(x) ((x) >= '0' && (x) <= '8')

#define VB_RAW_CNT_NONE     0
#define VB_LINEAR_RAW_CNT   5
#define VB_WDR_RAW_CNT      8
#define VB_MULTI_RAW_CNT    15
#define VB_YUV_ROUTE_CNT    10
#define VB_DOUBLE_YUV_CNT   15
#define VB_MULTI_YUV_CNT    30

static sample_vo_cfg g_vo_cfg = {
    .vo_dev            = SAMPLE_VO_DEV_UHD,
    .vo_intf_type      = OT_VO_INTF_HDMI,
    .intf_sync         = OT_VO_OUT_1080P60,
    .bg_color          = COLOR_RGB_BLACK,
    .pix_format        = OT_PIXEL_FORMAT_YVU_SEMIPLANAR_420,
    .disp_rect         = {0, 0, 1920, 1080},
    .image_size        = {1920, 1080},
    .vo_part_mode      = OT_VO_PARTITION_MODE_SINGLE,
    .dis_buf_len       = 3, /* 3: def buf len for single */
    .dst_dynamic_range = OT_DYNAMIC_RANGE_SDR8,
    .vo_mode           = VO_MODE_1MUX,
    .compress_mode     = OT_COMPRESS_MODE_NONE,
};

static sample_comm_venc_chn_param g_camera_venc_param = {
    .frame_rate           = 30, /* 30 is a number */
    .stats_time           = 1,  /* 1 is a number */
    .gop                  = 10, /* shorter GOP for lower RTSP join latency */
    .venc_size            = {1920, 1080},
    .size                 = PIC_1080P,
    .profile              = 0,
    .is_rcn_ref_share_buf = TD_FALSE,
    .gop_attr             = {
        .gop_mode = OT_VENC_GOP_MODE_NORMAL_P,
        .normal_p = {2},
    },
    .type                 = OT_PT_H264,
    .rc_mode              = SAMPLE_RC_VBR,
};

static td_void sample_dtof_rtsp_client_event(int index, int connected, const char* ip, int port)
{
    if (index != 0) {
        return;
    }
    sample_print("rtsp client event index=%d connected=%d peer=%s:%d\n",
        index, connected, ip == TD_NULL ? "" : ip, port);
    if (connected != 0 && g_camera_venc_started == TD_TRUE) {
        (td_void)sample_comm_request_idr(0, TD_TRUE);
    }
}

static td_void sample_get_char(td_void)
{
    if (g_sig_flag == 1) {
        return;
    }

    sample_pause();
}

static td_void sample_dtof_get_default_vb_config(ot_size *size, ot_vb_cfg *vb_cfg, ot_vi_video_mode video_mode,
    td_u32 yuv_cnt, td_u32 raw_cnt)
{
    ot_vb_calc_cfg calc_cfg;
    ot_pic_buf_attr buf_attr;

    (td_void)memset_s(vb_cfg, sizeof(ot_vb_cfg), 0, sizeof(ot_vb_cfg));
    vb_cfg->max_pool_cnt = 128; /* 128 blks */

    /* default YUV pool: SP420 + compress_seg */
    buf_attr.width         = size->width;
    buf_attr.height        = size->height;
    buf_attr.align         = OT_DEFAULT_ALIGN;
    buf_attr.bit_width     = OT_DATA_BIT_WIDTH_8;
    buf_attr.pixel_format  = OT_PIXEL_FORMAT_YVU_SEMIPLANAR_420;
    buf_attr.compress_mode = OT_COMPRESS_MODE_SEG;
    ot_common_get_pic_buf_cfg(&buf_attr, &calc_cfg);

    vb_cfg->common_pool[0].blk_size = calc_cfg.vb_size;
    vb_cfg->common_pool[0].blk_cnt  = yuv_cnt;

    /* default raw pool: raw12bpp + compress_line */
#if defined(DTOF_FORCE_RAW10_NONE)
    buf_attr.bit_width     = OT_DATA_BIT_WIDTH_10;
    buf_attr.pixel_format  = OT_PIXEL_FORMAT_RGB_BAYER_10BPP;
    buf_attr.compress_mode = OT_COMPRESS_MODE_NONE;
#elif defined(DTOF_FORCE_RAW12_NONE)
    buf_attr.bit_width     = OT_DATA_BIT_WIDTH_12;
    buf_attr.pixel_format  = OT_PIXEL_FORMAT_RGB_BAYER_12BPP;
    buf_attr.compress_mode = OT_COMPRESS_MODE_NONE;
#else
    buf_attr.pixel_format  = OT_PIXEL_FORMAT_RGB_BAYER_12BPP;
    buf_attr.compress_mode = (video_mode == OT_VI_VIDEO_MODE_NORM ? OT_COMPRESS_MODE_LINE : OT_COMPRESS_MODE_NONE);
#endif
    ot_common_get_pic_buf_cfg(&buf_attr, &calc_cfg);
    vb_cfg->common_pool[1].blk_size = calc_cfg.vb_size;
    vb_cfg->common_pool[1].blk_cnt  = raw_cnt;
}

static td_s32 sample_dtof_sys_init(sample_sns_type sns_type, ot_vi_vpss_mode_type mode_type, ot_vi_video_mode video_mode,
    td_u32 yuv_cnt, td_u32 raw_cnt)
{
    td_s32 ret;
    ot_size size;
    ot_vb_cfg vb_cfg;
    td_u32 supplement_config;

    sample_comm_vi_get_size_by_sns_type(sns_type, &size);
    sample_dtof_get_default_vb_config(&size, &vb_cfg, video_mode, yuv_cnt, raw_cnt);

    supplement_config = OT_VB_SUPPLEMENT_BNR_MOT_MASK;
    ret = sample_comm_sys_init_with_vb_supplement(&vb_cfg, supplement_config);
    if (ret != TD_SUCCESS) {
        return TD_FAILURE;
    }

    ret = sample_comm_vi_set_vi_vpss_mode(mode_type, video_mode);
    if (ret != TD_SUCCESS) {
        return TD_FAILURE;
    }

    return TD_SUCCESS;
}

static td_s32 sample_dtof_start_vpss(ot_vpss_grp grp, ot_size *in_size)
{
    td_s32 ret;
    ot_vpss_grp_attr grp_attr;
    ot_vpss_chn_attr chn_attr;
    td_bool chn_enable[OT_VPSS_MAX_PHYS_CHN_NUM] = {TD_TRUE, TD_FALSE, TD_FALSE, TD_FALSE};

    sample_comm_vpss_get_default_grp_attr(&grp_attr);
    grp_attr.max_width  = in_size->width;
    grp_attr.max_height = in_size->height;
    sample_comm_vpss_get_default_chn_attr(&chn_attr);
    chn_attr.width  = in_size->width;
    chn_attr.height = in_size->height;
    if (g_camera_rtsp_rotate_180 == TD_TRUE) {
        chn_attr.mirror_en = TD_TRUE;
        chn_attr.flip_en = TD_TRUE;
        sample_print("camera rtsp rotate180 enabled: vpss mirror+flip\n");
    }

    ret = sample_common_vpss_start(grp, chn_enable, &grp_attr, &chn_attr, OT_VPSS_MAX_PHYS_CHN_NUM);
    if (ret != TD_SUCCESS) {
        return ret;
    }

    return TD_SUCCESS;
}

static td_void sample_dtof_stop_vpss(ot_vpss_grp grp)
{
    td_bool chn_enable[OT_VPSS_MAX_PHYS_CHN_NUM] = {TD_TRUE, TD_FALSE, TD_FALSE, TD_FALSE};

    sample_common_vpss_stop(grp, chn_enable, OT_VPSS_MAX_PHYS_CHN_NUM);
}

static td_s32 sample_dtof_start_vo(ot_vpss_grp vpss_grp[], td_u32 grp_num, const ot_size *in_size)
{
    td_u32 i;
    td_s32 ret;
    sample_vo_mode vo_mode = VO_MODE_1MUX;
    const ot_vpss_chn vpss_chn = 0;
    const ot_vo_layer vo_layer = 0;
    ot_vo_chn vo_chn[4] = {0, 1, 2, 3};     /* 4: max chn num, 0/1/2/3 chn id */

    if (grp_num > 1) {
        vo_mode = VO_MODE_4MUX;
    }

    g_vo_cfg.vo_mode = vo_mode;
    ret = sample_comm_vo_start_vo(&g_vo_cfg);
    if (ret != TD_SUCCESS) {
        goto start_vo_failed;
    }

    for (i = 0; i < grp_num; i++) {
        sample_comm_vpss_bind_vo(vpss_grp[i], vpss_chn, vo_layer, vo_chn[i]);
    }
    return TD_SUCCESS;

start_vo_failed:
    return TD_FAILURE;
}

static td_void sample_dtof_stop_vo(ot_vpss_grp vpss_grp[], td_u32 grp_num)
{
    td_u32 i;
    const ot_vpss_chn vpss_chn = 0;
    const ot_vo_layer vo_layer = 0;
    ot_vo_chn vo_chn[4] = {0, 1, 2, 3};     /* 4: max chn num, 0/1/2/3 chn id */

    for (i = 0; i < grp_num; i++) {
        sample_comm_vpss_un_bind_vo(vpss_grp[i], vpss_chn, vo_layer, vo_chn[i]);
    }

    sample_comm_vo_stop_vo(&g_vo_cfg);
}

static td_s32 sample_dtof_start_camera_rtsp(ot_vpss_grp vpss_grp, const ot_size *in_size)
{
    td_s32 ret;
    const ot_vpss_chn vpss_chn = 0;
    ot_venc_chn venc_chn[1] = {0};

    g_camera_venc_param.venc_size.width = in_size->width;
    g_camera_venc_param.venc_size.height = in_size->height;
    g_camera_venc_param.size = sample_comm_sys_get_pic_enum(in_size);

    sample_comm_venc_set_push_rtsp(TD_TRUE);

    if (rtsp_server_start("0.0.0.0", 554) != 1) { /* 554: rtsp default port */
        sample_print("start rtsp server failed\n");
        goto rtsp_start_failed;
    }

    rtsp_set_client_event_cb(sample_dtof_rtsp_client_event);

    if (rtsp_session_create(0, g_camera_venc_param.type == OT_PT_H265 ? 1 : 0) != 1) { /* live0 */
        sample_print("create rtsp session live0 failed\n");
        goto rtsp_session_failed;
    }

    ret = sample_comm_venc_start(venc_chn[0], &g_camera_venc_param);
    if (ret != TD_SUCCESS) {
        sample_print("start camera venc failed ret: 0x%x\n", ret);
        goto venc_start_failed;
    }

    ret = sample_comm_venc_start_get_stream(venc_chn, 1);
    if (ret != TD_SUCCESS) {
        sample_print("start camera venc stream failed ret: 0x%x\n", ret);
        goto venc_stream_failed;
    }

    ret = sample_comm_vpss_bind_venc(vpss_grp, vpss_chn, venc_chn[0]);
    if (ret != TD_SUCCESS) {
        sample_print("bind vpss to venc failed ret: 0x%x\n", ret);
        goto venc_bind_failed;
    }

    g_camera_venc_started = TD_TRUE;
    (td_void)sample_comm_request_idr(venc_chn[0], TD_TRUE);
    sample_print("camera rtsp stable ready: codec=%s gop=%u url=rtsp://192.168.137.2:554/live0\n",
        g_camera_venc_param.type == OT_PT_H265 ? "h265" : "h264", g_camera_venc_param.gop);
    return TD_SUCCESS;

venc_bind_failed:
    sample_comm_venc_stop_get_stream(1);
venc_stream_failed:
    sample_comm_venc_stop(venc_chn[0]);
venc_start_failed:
rtsp_session_failed:
    rtsp_server_stop();
rtsp_start_failed:
    sample_comm_venc_set_push_rtsp(TD_FALSE);
    return TD_FAILURE;
}

static td_void sample_dtof_stop_camera_rtsp(ot_vpss_grp vpss_grp)
{
    const ot_vpss_chn vpss_chn = 0;
    const ot_venc_chn venc_chn = 0;

    sample_comm_vpss_un_bind_venc(vpss_grp, vpss_chn, venc_chn);
    g_camera_venc_started = TD_FALSE;
    sample_comm_venc_stop_get_stream(1);
    sample_comm_venc_stop(venc_chn);
    rtsp_server_stop();
    sample_comm_venc_set_push_rtsp(TD_FALSE);
}

static td_void sample_dtof_get_one_sensor_vi_cfg(sample_sns_type sns_type, sample_vi_cfg *vi_cfg, int sensor_num)
{
    if (sensor_num == 0) {
        const ot_vi_dev vi_dev = 0; /* dev0 for sensor0 */
        const ot_vi_pipe vi_pipe = 0; /* dev0 bind pipe0 */

        sample_comm_vi_get_default_vi_cfg(sns_type, vi_cfg);

        vi_cfg->sns_info.bus_id = 5; /* i2c5 */
        vi_cfg->sns_info.sns_clk_src = 0;
        vi_cfg->sns_info.sns_rst_src = 0;

        sample_comm_vi_get_mipi_info_by_dev_id(sns_type, vi_dev, &vi_cfg->mipi_info);
        vi_cfg->mipi_info.divide_mode = LANE_DIVIDE_MODE_2;  //4 lane + 2lane + 2lane
        vi_cfg->dev_info.vi_dev = vi_dev;
        vi_cfg->bind_pipe.pipe_id[0] = vi_pipe;
        vi_cfg->grp_info.grp_num = 1;
        vi_cfg->grp_info.fusion_grp[0] = 0;
        vi_cfg->grp_info.fusion_grp_attr[0].pipe_id[0] = vi_pipe;
    } else if (sensor_num == 1) {
        const ot_vi_dev vi_dev = 2; /* dev2 for sensor1 */
        const ot_vi_pipe vi_pipe = 0; /* dev2 bind pipe0 */

        sample_comm_vi_get_default_vi_cfg(sns_type, vi_cfg);

        vi_cfg->sns_info.bus_id = 7; /* i2c7 */
        vi_cfg->sns_info.sns_clk_src = 1;
        vi_cfg->sns_info.sns_rst_src = 1;

        sample_comm_vi_get_mipi_info_by_dev_id(sns_type, vi_dev, &vi_cfg->mipi_info);
        vi_cfg->mipi_info.divide_mode = LANE_DIVIDE_MODE_2;  //4 lane + 2lane + 2lane
        vi_cfg->dev_info.vi_dev = vi_dev;
        vi_cfg->bind_pipe.pipe_id[0] = vi_pipe;
        vi_cfg->grp_info.grp_num = 1;
        vi_cfg->grp_info.fusion_grp[0] = 0;
        vi_cfg->grp_info.fusion_grp_attr[0].pipe_id[0] = vi_pipe;
    }
}

static td_void sample_dtof_get_one_dtof_sensor_vi_cfg(sample_sns_type sns_type, sample_vi_cfg *vi_cfg, int sensor_num)
{
    if (sensor_num == 2) {
        const ot_vi_dev vi_dev = 2; /* dev2 for sensor2 */
        const ot_vi_pipe vi_pipe = 1; /* dev2 bind pipe1 */

        sample_comm_vi_get_default_vi_cfg(sns_type, vi_cfg);

        vi_cfg->sns_info.bus_id = 4; /* i2c4 */
        vi_cfg->sns_info.sns_clk_src = 1;
        vi_cfg->sns_info.sns_rst_src = 1;

        sample_comm_vi_get_mipi_info_by_dev_id(sns_type, vi_dev, &vi_cfg->mipi_info);
        vi_cfg->mipi_info.divide_mode = LANE_DIVIDE_MODE_2;  //4 lane + 2lane + 2lane
        vi_cfg->dev_info.vi_dev = vi_dev;
        vi_cfg->bind_pipe.pipe_id[0] = vi_pipe;
        vi_cfg->grp_info.grp_num = 1;
        vi_cfg->grp_info.fusion_grp[0] = 0;
        vi_cfg->grp_info.fusion_grp_attr[0].pipe_id[0] = vi_pipe;
        vi_cfg->pipe_info[0].isp_need_run = TD_FALSE;
        vi_cfg->pipe_info[0].chn_need_start = TD_TRUE;
        vi_cfg->pipe_info[0].pipe_attr.pipe_bypass_mode = OT_VI_PIPE_BYPASS_BE;
#if defined(DTOF_FORCE_RAW10_NONE)
        vi_cfg->pipe_info[0].pipe_attr.pixel_format = OT_PIXEL_FORMAT_RGB_BAYER_10BPP;
        vi_cfg->pipe_info[0].pipe_attr.compress_mode = OT_COMPRESS_MODE_NONE;
#elif defined(DTOF_FORCE_RAW12_NONE)
        vi_cfg->pipe_info[0].pipe_attr.pixel_format = OT_PIXEL_FORMAT_RGB_BAYER_12BPP;
        vi_cfg->pipe_info[0].pipe_attr.compress_mode = OT_COMPRESS_MODE_NONE;
#endif
    } else if (sensor_num == 3) {
        const ot_vi_dev vi_dev = 3; /* dev3 for sensor3 */
        const ot_vi_pipe vi_pipe = 1; /* dev3 bind pipe1 */

        sample_comm_vi_get_default_vi_cfg(sns_type, vi_cfg);

        vi_cfg->sns_info.bus_id = 5; /* i2c5 */
        vi_cfg->sns_info.sns_clk_src = 1;
        vi_cfg->sns_info.sns_rst_src = 1;

        sample_comm_vi_get_mipi_info_by_dev_id(sns_type, vi_dev, &vi_cfg->mipi_info);
        vi_cfg->mipi_info.divide_mode = LANE_DIVIDE_MODE_2;  //4 lane + 2lane + 2lane
        vi_cfg->dev_info.vi_dev = vi_dev;
        vi_cfg->bind_pipe.pipe_id[0] = vi_pipe;
        vi_cfg->grp_info.grp_num = 1;
        vi_cfg->grp_info.fusion_grp[0] = 0;
        vi_cfg->grp_info.fusion_grp_attr[0].pipe_id[0] = vi_pipe;
        vi_cfg->pipe_info[0].isp_need_run = TD_FALSE;
        vi_cfg->pipe_info[0].chn_need_start = TD_TRUE;
        vi_cfg->pipe_info[0].pipe_attr.pipe_bypass_mode = OT_VI_PIPE_BYPASS_BE;
#if defined(DTOF_FORCE_RAW10_NONE)
        vi_cfg->pipe_info[0].pipe_attr.pixel_format = OT_PIXEL_FORMAT_RGB_BAYER_10BPP;
        vi_cfg->pipe_info[0].pipe_attr.compress_mode = OT_COMPRESS_MODE_NONE;
#elif defined(DTOF_FORCE_RAW12_NONE)
        vi_cfg->pipe_info[0].pipe_attr.pixel_format = OT_PIXEL_FORMAT_RGB_BAYER_12BPP;
        vi_cfg->pipe_info[0].pipe_attr.compress_mode = OT_COMPRESS_MODE_NONE;
#endif
    }
}

static td_s32 sample_dtof_start_multi_vi_vpss(sample_sns_type sns_type, sample_vi_cfg *vi_cfg, ot_vpss_grp *vpss_grp,
                                             td_s32 dev_num, td_s32 grp_num)
{
    td_s32 ret;
    td_s32 i, j;
    ot_size in_size;

    if (dev_num != grp_num) {
        return TD_FAILURE;
    }

    sample_comm_vi_get_size_by_sns_type(sns_type, &in_size);

    for (i = 0; i < dev_num; i++) {
        ret = sample_comm_vi_start_vi(&vi_cfg[i]);
        if (ret != TD_SUCCESS) {
        goto start_vi_failed;
        }
    }

    for (i = 0; i < grp_num; i++) {
        sample_comm_vi_bind_vpss(i, 0, vpss_grp[i], 0);
    }

    for (i = 0; i < grp_num; i++) {
        ret = sample_dtof_start_vpss(vpss_grp[i], &in_size);
        if (ret != TD_SUCCESS) {
            goto start_vpss_failed;
        }
    }

    return TD_SUCCESS;

start_vpss_failed:
    for (j = i - 1; j >= 0; j--) {
        sample_dtof_stop_vpss(vpss_grp[j]);
    }

    for (i = 0; i < grp_num; i++) {
        sample_comm_vi_un_bind_vpss(i, 0, vpss_grp[i], 0);
    }

start_vi_failed:
    for (j = i - 1; j >= 0; j--) {
        sample_comm_vi_stop_vi(&vi_cfg[j]);
    }

    return TD_FAILURE;
}

/*
    1路 4lane sensor

    EULER_1R2D    sensor0 ---> i2c5 clk0 rtsn0
    EULER_1R2D J3 sensor2 ---> i2c4
    EULER_1R2D J4 sensor3 ---> i2c5

*/

static td_s32 sample_dtof_one_sensor(int sensor_num, td_bool enable_camera_rtsp)
{
    td_s32 ret;
    td_bool camera_rtsp_started = TD_FALSE;

    ot_vi_vpss_mode_type mode_type = OT_VI_OFFLINE_VPSS_OFFLINE;
    ot_vi_video_mode video_mode = OT_VI_VIDEO_MODE_NORM;
    const ot_vi_pipe vi_pipe = 0;
    const ot_vi_chn vi_chn = 0;
    ot_vpss_grp vpss_grp[1] = {0};
    const td_u32 grp_num = 1;
    const ot_vpss_chn vpss_chn = 0;
    sample_vi_cfg vi_cfg[1];
    sample_sns_type sns_type = SENSOR0_TYPE;
    ot_size in_size;

    g_camera_rtsp_rotate_180 = enable_camera_rtsp;

    ret = sample_dtof_sys_init(sns_type, mode_type, video_mode, VB_YUV_ROUTE_CNT, VB_RAW_CNT_NONE);
    if (ret != TD_SUCCESS) {
        goto sys_init_failed;
    }

    sample_dtof_get_one_sensor_vi_cfg(sns_type, &vi_cfg[0], sensor_num);
    ret = sample_dtof_start_multi_vi_vpss(sns_type, vi_cfg, vpss_grp, 1, 1);/* start 1 route */
    if (ret != TD_SUCCESS) {
        goto start_vi_vpss_failed;
    }

    sample_comm_vi_get_size_by_sns_type(sns_type, &in_size);
    ret = sample_dtof_start_vo(vpss_grp, grp_num, &in_size);
    if (ret != TD_SUCCESS) {
        goto start_vo_failed;
    }

    if (enable_camera_rtsp == TD_TRUE) {
        ret = sample_dtof_start_camera_rtsp(vpss_grp[0], &in_size);
        if (ret != TD_SUCCESS) {
            goto start_camera_rtsp_failed;
        }
        camera_rtsp_started = TD_TRUE;
    }

    sample_get_char();

    if (camera_rtsp_started == TD_TRUE) {
        sample_dtof_stop_camera_rtsp(vpss_grp[0]);
    }

start_camera_rtsp_failed:
    sample_dtof_stop_vo(vpss_grp, grp_num);

start_vo_failed:
    sample_dtof_stop_vpss(vpss_grp[0]);
    sample_comm_vi_un_bind_vpss(vi_pipe, vi_chn, vpss_grp[0], vpss_chn);
    sample_comm_vi_stop_vi(&vi_cfg[0]);
start_vi_vpss_failed:
    sample_comm_sys_exit();
sys_init_failed:
    g_camera_rtsp_rotate_180 = TD_FALSE;
    return ret;
}

/*
    1路 1lane sensor

    EULER_1R2D    sensor0 ---> i2c5 clk0 rtsn0
    EULER_1R2D J3 sensor2 ---> i2c4
    EULER_1R2D J4 sensor3 ---> i2c5

    dtof
*/

static td_s32 sample_dtof_one_dtof_sensor(int sensor_num, td_char* server_ip)
{
    td_s32 ret;

    ot_vi_vpss_mode_type mode_type = OT_VI_OFFLINE_VPSS_OFFLINE;
    ot_vi_video_mode video_mode = OT_VI_VIDEO_MODE_NORM;
    const ot_vi_pipe vi_pipe = 1;
    sample_vi_cfg vi_cfg[1];
    sample_sns_type sns_type = SENSOR2_TYPE;

    ret = sample_dtof_sys_init(sns_type, mode_type, video_mode, VB_DOUBLE_YUV_CNT, VB_WDR_RAW_CNT);
    if (ret != TD_SUCCESS) {
        goto sys_init_failed;
    }

    ret = gs1860_read_ini_file(GS1860_REG_INI_FILE);
    if (ret != TD_SUCCESS) {
        sample_print("load gs1860 ini failed\n");
        goto start_dtof_failed;
    }

    sample_dtof_get_one_dtof_sensor_vi_cfg(sns_type, &vi_cfg[0], sensor_num);

    ret = sample_comm_vi_start_vi(&vi_cfg[0]);
    if (ret != TD_SUCCESS) {
        goto start_dtof_failed;
    }

    ret = dtof_init(vi_pipe, server_ip);
    if (ret != TD_SUCCESS) {
        sample_print("dtof init failed\n");
        goto dtof_init_failed;
    }

    ot_vi_dev vi_dev = sensor_num;
    ret = vi_bayerdump(vi_pipe, vi_dev);
    if (ret != TD_SUCCESS) {
        sample_print("start vi_bayerdump failed ret: 0x%x !\n", ret);
        goto vi_dump_failed;
    }

    sample_get_char();

vi_dump_failed:
    dtof_deinit();
dtof_init_failed:
    sample_comm_vi_stop_vi(&vi_cfg[0]);
start_dtof_failed:
    sample_comm_sys_exit();
sys_init_failed:
    return ret;
}

/*
    1路 4lane sensor + 1路 1lane dtof

    EULER_1R2D sensor0 ---> i2c5 clk0 rtsn0
    EULER_1R2D J3 sensor2 ---> i2c4
    EULER_1R2D J4 sensor3 ---> i2c5

    sensor0 + dtof
*/
static td_s32 sample_dtof_dtof_and_rgb(int sensor_num, td_char* server_ip, td_bool enable_camera_rtsp)
{
    td_s32 ret;
    td_bool camera_rtsp_started = TD_FALSE;

    ot_vi_vpss_mode_type mode_type = OT_VI_OFFLINE_VPSS_OFFLINE;
    ot_vi_video_mode video_mode = OT_VI_VIDEO_MODE_NORM;
    const ot_vi_pipe vi_pipe[2] = {0, 1};
    const ot_vi_chn vi_chn = 0;
    ot_vpss_grp vpss_grp[1] = {0};
    const td_u32 grp_num = 1;
    const ot_vpss_chn vpss_chn = 0;
    sample_vi_cfg vi_cfg[2];
    sample_sns_type sns_type = SENSOR0_TYPE;
    ot_size in_size;

    g_camera_rtsp_rotate_180 = enable_camera_rtsp;

    //RGB Sensor0
    ret = sample_dtof_sys_init(sns_type, mode_type, video_mode, VB_DOUBLE_YUV_CNT, VB_WDR_RAW_CNT);
    if (ret != TD_SUCCESS) {
        goto sys_init_failed;
    }

    sample_dtof_get_one_sensor_vi_cfg(sns_type, &vi_cfg[0], 0);  //sensor0
    ret = sample_dtof_start_multi_vi_vpss(sns_type, &vi_cfg[0], vpss_grp, 1, 1);/* start 1 route */
    if (ret != TD_SUCCESS) {
        goto start_vi_vpss_failed;
    }

    sample_comm_vi_get_size_by_sns_type(sns_type, &in_size);
    ret = sample_dtof_start_vo(vpss_grp, grp_num, &in_size);
    if (ret != TD_SUCCESS) {
        goto start_vo_failed;
    }

    if (enable_camera_rtsp == TD_TRUE) {
        ret = sample_dtof_start_camera_rtsp(vpss_grp[0], &in_size);
        if (ret != TD_SUCCESS) {
            goto start_camera_rtsp_failed;
        }
        camera_rtsp_started = TD_TRUE;
    }

    //DTOF
    sns_type = SENSOR2_TYPE;

    ret = gs1860_read_ini_file(GS1860_REG_INI_FILE);
    if (ret != TD_SUCCESS) {
        sample_print("load gs1860 ini failed\n");
        goto start_dtof_failed;
    }

    sample_dtof_get_one_dtof_sensor_vi_cfg(sns_type, &vi_cfg[1], sensor_num);
    ret = sample_comm_vi_start_vi(&vi_cfg[1]);
    if (ret != TD_SUCCESS) {
        goto start_dtof_failed;
    }

    ret = dtof_init(vi_pipe[1], server_ip);
    if (ret != TD_SUCCESS) {
        sample_print("dtof init failed\n");
        goto dtof_init_failed;
    }

    ot_vi_dev vi_dev = sensor_num;
    ret = vi_bayerdump(vi_pipe[1], vi_dev);
    if (ret != TD_SUCCESS) {
        sample_print("start vi_bayerdump failed ret: 0x%x !\n", ret);
        goto vi_dump_failed;
    }

    sample_get_char();

vi_dump_failed:
    dtof_deinit();
dtof_init_failed:
    sample_comm_vi_stop_vi(&vi_cfg[1]);
start_dtof_failed:
    if (camera_rtsp_started == TD_TRUE) {
        sample_dtof_stop_camera_rtsp(vpss_grp[0]);
    }
start_camera_rtsp_failed:
    sample_dtof_stop_vo(vpss_grp, grp_num);
start_vo_failed:
    sample_dtof_stop_vpss(vpss_grp[0]);
    sample_comm_vi_un_bind_vpss(vi_pipe[0], vi_chn, vpss_grp[0], vpss_chn);
    sample_comm_vi_stop_vi(&vi_cfg[0]);
start_vi_vpss_failed:
    sample_comm_sys_exit();
sys_init_failed:
    g_camera_rtsp_rotate_180 = TD_FALSE;
    return ret;
}

/*
    2路 1lane dtof

    EULER_1R2D    sensor0 ---> i2c5 clk0 rtsn0
    EULER_1R2D J3 sensor2 ---> i2c4
    EULER_1R2D J4 sensor3 ---> i2c5

    dtof0 + dtof1
*/
static td_s32 sample_dtof_two_dtof(td_char* server_ip)
{
    td_s32 ret;

    ot_vi_vpss_mode_type mode_type = OT_VI_OFFLINE_VPSS_OFFLINE;
    ot_vi_video_mode video_mode = OT_VI_VIDEO_MODE_NORM;
    ot_vi_dev vi_dev[2] = {2, 3};
    const ot_vi_pipe vi_pipe[2] = {2, 3};
    sample_vi_cfg vi_cfg[2];
    sample_sns_type sns_type = SENSOR2_TYPE;

    ret = sample_dtof_sys_init(sns_type, mode_type, video_mode, VB_DOUBLE_YUV_CNT, VB_WDR_RAW_CNT);
    if (ret != TD_SUCCESS) {
        goto sys_init_failed;
    }

    ret = gs1860_read_ini_file(GS1860_REG_INI_FILE);
    if (ret != TD_SUCCESS) {
        sample_print("load gs1860 ini failed\n");
        goto start_dtof0_failed;
    }

    //dtof0
    sample_dtof_get_one_dtof_sensor_vi_cfg(sns_type, &vi_cfg[0], vi_dev[0]);

    vi_cfg[0].bind_pipe.pipe_id[0] = vi_pipe[0];
    vi_cfg[0].grp_info.fusion_grp_attr[0].pipe_id[0] = vi_pipe[0];

    ret = sample_comm_vi_start_vi(&vi_cfg[0]);
    if (ret != TD_SUCCESS) {
        goto start_dtof0_failed;
    }

    //dtof1
    sample_dtof_get_one_dtof_sensor_vi_cfg(sns_type, &vi_cfg[1], vi_dev[1]);

    vi_cfg[1].bind_pipe.pipe_id[0] = vi_pipe[1];
    vi_cfg[1].grp_info.fusion_grp_attr[0].pipe_id[0] = vi_pipe[1];

    ret = sample_comm_vi_start_vi(&vi_cfg[1]);
    if (ret != TD_SUCCESS) {
        goto start_dtof1_failed;
    }

    //udp默认发送dtof0
    ret = dtof_init(vi_pipe[0], server_ip);
    if (ret != TD_SUCCESS) {
        sample_print("dtof init failed\n");
        goto dtof_init_failed;
    }

    ret = vi_bayerdump(vi_pipe[0], vi_dev[0]);
    if (ret != TD_SUCCESS) {
        sample_print("start vi_bayerdump failed ret: 0x%x !\n", ret);
        goto vi_dump_failed;
    }

    sample_get_char();

vi_dump_failed:
    dtof_deinit();
dtof_init_failed:
        sample_comm_vi_stop_vi(&vi_cfg[1]);
start_dtof1_failed:
        sample_comm_vi_stop_vi(&vi_cfg[0]);
start_dtof0_failed:
    sample_comm_sys_exit();
sys_init_failed:
    return ret;
}

/*
    1路 4lane sensor0 + 2路 1lane dtof

    EULER_1R2D    sensor0 ---> i2c5 clk0 rtsn0
    EULER_1R2D J3 sensor2 ---> i2c4
    EULER_1R2D J4 sensor3 ---> i2c5

    sensor0 + dtof0 + dtof1
*/
static td_s32 sample_dtof_two_dtof_and_rgb(td_char* server_ip)
{
    td_s32 ret;

    ot_vi_vpss_mode_type mode_type = OT_VI_OFFLINE_VPSS_OFFLINE;
    ot_vi_video_mode video_mode = OT_VI_VIDEO_MODE_NORM;
    const ot_vi_dev vi_dev[3] = {0, 2, 3};
    const ot_vi_pipe vi_pipe[3] = {0, 2, 3};
    const ot_vi_chn vi_chn = 0;
    ot_vpss_grp vpss_grp[1] = {0};
    const td_u32 grp_num = 1;
    const ot_vpss_chn vpss_chn = 0;
    sample_vi_cfg vi_cfg[3];
    sample_sns_type sns_type = SENSOR0_TYPE;
    ot_size in_size;

    //RGB Sensor0
    ret = sample_dtof_sys_init(sns_type, mode_type, video_mode, VB_DOUBLE_YUV_CNT, VB_WDR_RAW_CNT);
    if (ret != TD_SUCCESS) {
        goto sys_init_failed;
    }

    sample_dtof_get_one_sensor_vi_cfg(sns_type, &vi_cfg[0], 0);  //sensor0
    ret = sample_dtof_start_multi_vi_vpss(sns_type, &vi_cfg[0], vpss_grp, 1, 1);/* start 1 route */
    if (ret != TD_SUCCESS) {
        goto start_vi_vpss_failed;
    }

    sample_comm_vi_get_size_by_sns_type(sns_type, &in_size);
    ret = sample_dtof_start_vo(vpss_grp, grp_num, &in_size);
    if (ret != TD_SUCCESS) {
        goto start_vo_failed;
    }

    //DTOF
    sns_type = SENSOR2_TYPE;

    ret = gs1860_read_ini_file(GS1860_REG_INI_FILE);
    if (ret != TD_SUCCESS) {
        sample_print("load gs1860 ini failed\n");
        goto start_dtof0_failed;
    }

    //dtof0
    sample_dtof_get_one_dtof_sensor_vi_cfg(sns_type, &vi_cfg[1], vi_dev[1]);

    vi_cfg[1].bind_pipe.pipe_id[0] = vi_pipe[1];
    vi_cfg[1].grp_info.fusion_grp_attr[0].pipe_id[0] = vi_pipe[1];

    ret = sample_comm_vi_start_vi(&vi_cfg[1]);
    if (ret != TD_SUCCESS) {
        goto start_dtof0_failed;
    }

    //dtof1
    sample_dtof_get_one_dtof_sensor_vi_cfg(sns_type, &vi_cfg[2], vi_dev[2]);

    vi_cfg[2].bind_pipe.pipe_id[0] = vi_pipe[2];
    vi_cfg[2].grp_info.fusion_grp_attr[0].pipe_id[0] = vi_pipe[2];

    ret = sample_comm_vi_start_vi(&vi_cfg[2]);
    if (ret != TD_SUCCESS) {
        goto start_dtof1_failed;
    }

    //udp默认发送dtof0
    ret = dtof_init(vi_pipe[1], server_ip);
    if (ret != TD_SUCCESS) {
        sample_print("dtof init failed\n");
        goto dtof_init_failed;
    }

    ret = vi_bayerdump(vi_pipe[1], vi_dev[1]);
    if (ret != TD_SUCCESS) {
        sample_print("start vi_bayerdump failed ret: 0x%x !\n", ret);
        goto vi_dump_failed;
    }

    sample_get_char();

vi_dump_failed:
    dtof_deinit();
dtof_init_failed:
    sample_comm_vi_stop_vi(&vi_cfg[2]);
start_dtof1_failed:
    sample_comm_vi_stop_vi(&vi_cfg[1]);
start_dtof0_failed:
    sample_dtof_stop_vo(vpss_grp, grp_num);
start_vo_failed:
    sample_dtof_stop_vpss(vpss_grp[0]);
    sample_comm_vi_un_bind_vpss(vi_pipe[0], vi_chn, vpss_grp[0], vpss_chn);
    sample_comm_vi_stop_vi(&vi_cfg[0]);
start_vi_vpss_failed:
    sample_comm_sys_exit();
sys_init_failed:
    return ret;
}

static td_void sample_dtof_usage(char *prg_name)
{
    printf("usage : %s <index> <dst_ip>\n", prg_name);
    printf("index:\n");
    printf("    (0) one sensor               4lane sensor0.\n");
    printf("    (1) one dtof0                1lane sensor2.\n");
    printf("    (2) one dtof1                1lane sensor3.\n");
    printf("    (3) sensor0 + dtof0          4lane sensor0 + 1lane sensor2.\n");
    printf("    (4) sensor0 + dtof1          4lane sensor0 + 1lane sensor3.\n");
    printf("    (5) two dtof                 1lane sensor2 + 1lane sensor3.\n");
    printf("    (6) one sensor + two dtof    4lane sensor0 + 1lane sensor2 + 1lane sensor3.\n");
    printf("    (7) sensor0 + dtof0 + rtsp   4lane sensor0 + 1lane sensor2 + rtsp live0.\n");
    printf("    (8) sensor0 + rtsp           4lane sensor0 + rtsp live0, no dtof init.\n");
    printf("dst_ip:\n");
    printf("    destination IP\n");
    printf("    example: 192.168.1.4\n\n");
}

static td_void sample_dtof_handle_sig(td_s32 signo)
{
    if (signo == SIGINT || signo == SIGTERM) {
        g_sig_flag = 1;
    }
}

static td_void sample_register_sig_handler(td_void (*sig_handle)(td_s32))
{
    struct sigaction sa;

    (td_void)memset_s(&sa, sizeof(struct sigaction), 0, sizeof(struct sigaction));
    sa.sa_handler = sig_handle;
    sa.sa_flags = 0;
    sigaction(SIGINT, &sa, TD_NULL);
    sigaction(SIGTERM, &sa, TD_NULL);
}

static td_s32 sample_dtof_execute_case(td_u32 case_index, char *dst_ip)
{
    td_s32 ret;

    switch (case_index) {
        case 0: /* 0 one sensor0 */
            ret = sample_dtof_one_sensor(0, TD_FALSE);
            break;
        case 1: /* 1 one dtof0 */
            ret = sample_dtof_one_dtof_sensor(2, dst_ip);
            break;
        case 2: /* 2 one dtof1 */
            ret = sample_dtof_one_dtof_sensor(3, dst_ip);
            break;
        case 3: /* 3 sensor0 + dtof0*/
            ret = sample_dtof_dtof_and_rgb(2, dst_ip, TD_FALSE);
            break;
        case 4: /* 4 sensor0 + dtof1*/
            ret = sample_dtof_dtof_and_rgb(3, dst_ip, TD_FALSE);
            break;
        case 5: /* 5 dtof0 + dtof1*/
            ret = sample_dtof_two_dtof(dst_ip);
            break;
        case 6: /* 6 sensor0 + dtof0 + dtof1*/
            ret = sample_dtof_two_dtof_and_rgb(dst_ip);
            break;
        case 7: /* 7 sensor0 + dtof0 + rtsp */
            ret = sample_dtof_dtof_and_rgb(2, dst_ip, TD_TRUE);
            break;
        case 8: /* 8 sensor0 + rtsp only */
            ret = sample_dtof_one_sensor(0, TD_TRUE);
            break;
        default:
            ret = TD_FAILURE;
            break;
    }

    return ret;
}

#ifdef __LITEOS__
td_s32 app_main(td_s32 argc, td_char *argv[])
#else
td_s32 main(td_s32 argc, td_char *argv[])
#endif
{
    td_s32 ret;
    td_u32 index;
    td_char *dst_ip = TD_NULL;

    if (argc != 3) { /* 3:arg num */
        sample_dtof_usage(argv[0]);
        return TD_FAILURE;
    }

    if (!strncmp(argv[1], "-h", 2)) {
        sample_dtof_usage(argv[0]);
        return TD_FAILURE;
    }

    if (strlen(argv[1]) > 2 || strlen(argv[1]) <= 0 || !check_digit(argv[1][0]) || /* 2:arg len */
        (strlen(argv[1]) == 2 && (!check_digit(argv[1][1]) || argv[1][0] == '0'))) { /* 2:arg len */
        sample_dtof_usage(argv[0]);
        return TD_FAILURE;
    }

#ifndef __LITEOS__
    sample_register_sig_handler(sample_dtof_handle_sig);
#endif

    index = atoi(argv[1]);
    dst_ip = argv[2];

    ret = sample_dtof_execute_case(index, dst_ip);
    if ((ret == TD_SUCCESS) && (g_sig_flag == 0)) {
        printf("\033[0;32mprogram exit normally!\033[0;39m\n");
    } else {
        printf("\033[0;31mprogram exit abnormally!\033[0;39m\n");
    }

#ifdef __LITEOS__
    return ret;
#else
    exit(ret);
#endif
}
