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

#include "ot_scene.h"
#include "scene_loadparam.h"
#include "ot_scenecomm.h"
#include "ot_confaccess.h"
#include "gs1860_cmos.h"

#define VB_RAW_CNT_NONE     0
#define VB_LINEAR_RAW_CNT   5

#define STEP_LOG(fmt, ...) \
    do { \
        fprintf(stderr, "[OS08_DTOF_STEP] " fmt "\n", ##__VA_ARGS__); \
        fflush(stderr); \
    } while (0)

#define SCENE_PARAM_PATH "./param"
static ot_scene_param g_scene_param;

#define _SAVE_FILE_    1
#define _SUPPORT_RTSP_ 0

#ifndef SUPPORT_RGB
#define SUPPORT_RGB  1
#endif

#ifndef SUPPORT_DTOF
#define SUPPORT_DTOF 1
#endif

volatile sig_atomic_t g_sig_flag = 0;

static td_bool g_vo_started = TD_FALSE;

struct sensor_info {
    int i2c_bus;
} sns_info[4] = {
    {.i2c_bus = 7},
    {.i2c_bus = 5},
    {.i2c_bus = 4},
    {.i2c_bus = 6}
};

static sample_vo_cfg g_vo_cfg = {
    .vo_dev            = SAMPLE_VO_DEV_UHD,
    .vo_intf_type      = OT_VO_INTF_HDMI,
    .intf_sync         = OT_VO_OUT_1080P60,
    .bg_color          = COLOR_RGB_BLACK,
    .pix_format        = OT_PIXEL_FORMAT_YVU_SEMIPLANAR_420,
    .disp_rect         = {0, 0, 1920, 1080},
    .image_size        = {1920, 1080},
    .vo_part_mode      = OT_VO_PARTITION_MODE_SINGLE,
    .dis_buf_len       = 3,
    .dst_dynamic_range = OT_DYNAMIC_RANGE_SDR8,
    .vo_mode           = VO_MODE_1MUX,
    .compress_mode     = OT_COMPRESS_MODE_NONE,
};

static sample_comm_venc_chn_param g_venc_chn_param = {
    .frame_rate           = 30,
    .stats_time           = 1,
    .gop                  = 30,
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

static void sample_vio_handlesig(td_s32 signo)
{
    if (signo == SIGINT || signo == SIGTERM || signo == SIGKILL) {
        g_sig_flag = 1;
    }
}

static td_void sigint_handler(void (*func)(int))
{
    struct sigaction sa = {0};
    sa.sa_flags   = 0;
    sa.sa_handler = func;
    sigaction(SIGINT, &sa, TD_NULL);
    sigaction(SIGTERM, &sa, TD_NULL);
    sigaction(SIGKILL, &sa, TD_NULL);
}

static td_void sample_get_char(td_void)
{
    while (g_sig_flag == 0) {
        sleep(1);
    }
}

static td_s32 sample_vio_start_vo(sample_vo_mode vo_mode)
{
    g_vo_cfg.vo_mode = vo_mode;
    return sample_comm_vo_start_vo(&g_vo_cfg);
}

static td_void sample_vio_stop_vo(td_void)
{
    sample_comm_vo_stop_vo(&g_vo_cfg);
}

static td_s32 sample_vio_start_venc(ot_venc_chn venc_chn[], td_u32 chn_num, const ot_size *in_size)
{
    td_s32 i, ret;

    g_venc_chn_param.venc_size.width  = in_size->width;
    g_venc_chn_param.venc_size.height = in_size->height;
    g_venc_chn_param.size = sample_comm_sys_get_pic_enum(in_size);

    for (i = 0; i < (td_s32)chn_num; i++) {
        ret = sample_comm_venc_start(venc_chn[i], &g_venc_chn_param);
        if (ret != TD_SUCCESS) {
            goto exit;
        }
    }

    ret = sample_comm_venc_start_get_stream(venc_chn, chn_num);
    if (ret != TD_SUCCESS) {
        goto exit;
    }
    return TD_SUCCESS;

exit:
    for (i = i - 1; i >= 0; i--) {
        sample_comm_venc_stop(venc_chn[i]);
    }
    return TD_FAILURE;
}

static td_void sample_vio_stop_venc(ot_venc_chn venc_chn[], td_u32 chn_num)
{
    td_u32 i;
    sample_comm_venc_stop_get_stream(chn_num);
    for (i = 0; i < chn_num; i++) {
        sample_comm_venc_stop(venc_chn[i]);
    }
}

static td_void sample_vio_stop_venc_and_vo(ot_vpss_grp vpss_grp[], td_u32 grp_num)
{
    td_u32 i;
    const ot_vpss_chn vpss_chn = 0;
    const ot_vo_layer vo_layer = 0;
    ot_vo_chn  vo_chn[4]   = {0, 1, 2, 3};
    ot_venc_chn venc_chn[4] = {0, 1, 2, 3};

    for (i = 0; i < grp_num; i++) {
#if _SAVE_FILE_
        sample_comm_vpss_un_bind_venc(vpss_grp[i], vpss_chn, venc_chn[i]);
#endif
        if (g_vo_started) {
            sample_comm_vpss_un_bind_vo(vpss_grp[i], vpss_chn, vo_layer, vo_chn[i]);
        }
    }

#if _SAVE_FILE_
    sample_vio_stop_venc(venc_chn, grp_num);
#endif
    if (g_vo_started) {
        sample_vio_stop_vo();
        g_vo_started = TD_FALSE;
    }
}

static td_s32 sample_vio_start_venc_and_vo(ot_vpss_grp vpss_grp[], td_u32 grp_num, const ot_size *in_size)
{
    td_u32 i;
    td_s32 ret;
    sample_vo_mode vo_mode = VO_MODE_1MUX;
    const ot_vpss_chn vpss_chn = 0;
    const ot_vo_layer vo_layer = 0;
    ot_vo_chn  vo_chn[4]   = {0, 1, 2, 3};
    ot_venc_chn venc_chn[4] = {0, 1, 2, 3};

    if (grp_num > 1) {
        vo_mode = VO_MODE_4MUX;
    }

    /* VO (HDMI) is optional — board may be headless */
    ret = sample_vio_start_vo(vo_mode);
    if (ret != TD_SUCCESS) {
        printf("warning: VO (HDMI) start failed, continuing headless\n");
        g_vo_started = TD_FALSE;
    } else {
        g_vo_started = TD_TRUE;
    }

#if _SAVE_FILE_
    ret = sample_vio_start_venc(venc_chn, grp_num, in_size);
    if (ret != TD_SUCCESS) {
        if (g_vo_started) {
            sample_vio_stop_vo();
            g_vo_started = TD_FALSE;
        }
        return TD_FAILURE;
    }
#endif

    for (i = 0; i < grp_num; i++) {
#if _SAVE_FILE_
        sample_comm_vpss_bind_venc(vpss_grp[0], vpss_chn, venc_chn[i]);
#endif
        if (g_vo_started) {
            sample_comm_vpss_bind_vo(vpss_grp[0], vpss_chn, vo_layer, vo_chn[i]);
        }
    }

    return TD_SUCCESS;
}

static td_s32 sample_vio_start_vpss(ot_vpss_grp grp, ot_size *in_size)
{
    td_s32 ret;
    ot_low_delay_info low_delay_info;
    ot_vpss_grp_attr grp_attr;
    ot_vpss_chn_attr chn_attr;
    td_bool chn_enable[OT_VPSS_MAX_PHYS_CHN_NUM] = {TD_TRUE, TD_FALSE, TD_FALSE, TD_FALSE};

    sample_comm_vpss_get_default_grp_attr(&grp_attr);
    grp_attr.max_width  = in_size->width;
    grp_attr.max_height = in_size->height;

    sample_comm_vpss_get_default_chn_attr(&chn_attr);
    chn_attr.width  = in_size->width;
    chn_attr.height = in_size->height;

    ret = sample_common_vpss_start(grp, chn_enable, &grp_attr, &chn_attr, OT_VPSS_MAX_PHYS_CHN_NUM);
    if (ret != TD_SUCCESS) {
        return ret;
    }

    low_delay_info.enable     = TD_TRUE;
    low_delay_info.line_cnt   = 200;
    low_delay_info.one_buf_en = TD_FALSE;
    ret = ss_mpi_vpss_set_low_delay_attr(grp, 0, &low_delay_info);
    if (ret != TD_SUCCESS) {
        sample_common_vpss_stop(grp, chn_enable, OT_VPSS_MAX_PHYS_CHN_NUM);
        return ret;
    }
    return TD_SUCCESS;
}

static td_void sample_vio_stop_vpss(ot_vpss_grp grp)
{
    td_bool chn_enable[OT_VPSS_MAX_PHYS_CHN_NUM] = {TD_TRUE, TD_FALSE, TD_FALSE, TD_FALSE};
    sample_common_vpss_stop(grp, chn_enable, OT_VPSS_MAX_PHYS_CHN_NUM);
}

static td_s32 sample_vio_start_multi_vi_vpss_sensor_type(sample_vi_cfg *vi_cfg, ot_vpss_grp *vpss_grp,
    td_s32 dev_num, td_s32 grp_num, sample_sns_type sns_type)
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
        sample_comm_vi_bind_vpss(vi_cfg[i].bind_pipe.pipe_id[0], 0, vpss_grp[i], 0);
    }

    for (i = 0; i < grp_num; i++) {
        ret = sample_vio_start_vpss(vpss_grp[i], &in_size);
        if (ret != TD_SUCCESS) {
            goto start_vpss_failed;
        }
    }
    return TD_SUCCESS;

start_vpss_failed:
    for (j = i - 1; j >= 0; j--) {
        sample_vio_stop_vpss(vpss_grp[j]);
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

/* OS08A20 4-lane camera on sensor0 slot (i2c_bus=5, vi_dev=0, vi_pipe=0) */
static td_void sample_vi_get_one_sensor_vi_cfg_os08a20(sample_sns_type sns_type, sample_vi_cfg *vi_cfg0, int i2c_bus)
{
    if (i2c_bus == 5) {
        const ot_vi_dev  vi_dev  = 0;
        const ot_vi_pipe vi_pipe = 0;
        sample_comm_vi_get_default_vi_cfg(sns_type, vi_cfg0);
        vi_cfg0->sns_info.bus_id      = 5;
        vi_cfg0->sns_info.sns_clk_src = 0;
        vi_cfg0->sns_info.sns_rst_src = 0;
        sample_comm_vi_get_mipi_info_by_dev_id(sns_type, vi_dev, &vi_cfg0->mipi_info);
        /* NOTE: no LANE_DIVIDE_MODE_2 here — that was IMX347-specific */
        vi_cfg0->dev_info.vi_dev = vi_dev;
        vi_cfg0->bind_pipe.pipe_id[0] = vi_pipe;
        vi_cfg0->grp_info.fusion_grp_attr[0].pipe_id[0] = vi_pipe;
    }
    printf("======> camera i2c:%d sensor_slot:%d\n", vi_cfg0->sns_info.bus_id, vi_cfg0->sns_info.sns_clk_src);
}

/* GS1860 dToF on sensor2 slot (i2c_bus=4, vi_dev=2, vi_pipe=1, MIPI lane 4). */
static td_void sample_vi_get_one_dtof_vi_cfg_gs1860(sample_sns_type sns_type, sample_vi_cfg *vi_cfg0, int i2c_bus)
{
    if (i2c_bus == 4) {
        const ot_vi_dev  vi_dev  = 2;
        const ot_vi_pipe vi_pipe = 1;
        sample_comm_vi_get_default_vi_cfg(sns_type, vi_cfg0);
        vi_cfg0->sns_info.bus_id      = 4;
        vi_cfg0->sns_info.sns_clk_src = 1;
        vi_cfg0->sns_info.sns_rst_src = 1;

        sample_comm_vi_get_mipi_info_by_dev_id(sns_type, vi_dev, &vi_cfg0->mipi_info);
        vi_cfg0->mipi_info.divide_mode = LANE_DIVIDE_MODE_2;
        vi_cfg0->dev_info.vi_dev = vi_dev;
        vi_cfg0->bind_pipe.pipe_id[0] = vi_pipe;
        vi_cfg0->grp_info.grp_num = 1;
        vi_cfg0->grp_info.fusion_grp[0] = 0;
        vi_cfg0->grp_info.fusion_grp_attr[0].pipe_id[0] = vi_pipe;
        vi_cfg0->pipe_info[0].isp_need_run   = TD_FALSE;
        vi_cfg0->pipe_info[0].chn_need_start = TD_TRUE;
        vi_cfg0->pipe_info[0].pipe_attr.pipe_bypass_mode = OT_VI_PIPE_BYPASS_BE;
    }
    printf("======> dtof  i2c:%d sensor_slot:%d\n", vi_cfg0->sns_info.bus_id, vi_cfg0->sns_info.sns_clk_src);
}

static td_void sample_vi_get_default_vb_config(ot_size *size, ot_vb_cfg *vb_cfg, ot_vi_video_mode video_mode,
    td_u32 yuv_cnt, td_u32 raw_cnt)
{
    ot_vb_calc_cfg calc_cfg;
    ot_pic_buf_attr buf_attr;

    (td_void)memset_s(vb_cfg, sizeof(ot_vb_cfg), 0, sizeof(ot_vb_cfg));
    vb_cfg->max_pool_cnt = 128;

    buf_attr.width         = size->width;
    buf_attr.height        = size->height;
    buf_attr.align         = OT_DEFAULT_ALIGN;
    buf_attr.bit_width     = OT_DATA_BIT_WIDTH_8;
    buf_attr.pixel_format  = OT_PIXEL_FORMAT_YVU_SEMIPLANAR_420;
    buf_attr.compress_mode = OT_COMPRESS_MODE_SEG;
    ot_common_get_pic_buf_cfg(&buf_attr, &calc_cfg);
    vb_cfg->common_pool[0].blk_size = calc_cfg.vb_size;
    vb_cfg->common_pool[0].blk_cnt  = yuv_cnt;
    printf("width:%d, height:%d\n", buf_attr.width, buf_attr.height);
    printf("pool 0 blk_size:%d, blk_cnt:%d\n", vb_cfg->common_pool[0].blk_size, vb_cfg->common_pool[0].blk_cnt);

    buf_attr.pixel_format  = OT_PIXEL_FORMAT_RGB_BAYER_12BPP;
    buf_attr.compress_mode = (video_mode == OT_VI_VIDEO_MODE_NORM ? OT_COMPRESS_MODE_LINE : OT_COMPRESS_MODE_NONE);
    ot_common_get_pic_buf_cfg(&buf_attr, &calc_cfg);
    vb_cfg->common_pool[1].blk_size = calc_cfg.vb_size;
    vb_cfg->common_pool[1].blk_cnt  = raw_cnt;
    printf("pool 1 blk_size:%d, blk_cnt:%d\n", vb_cfg->common_pool[1].blk_size, vb_cfg->common_pool[1].blk_cnt);
}

static td_s32 sample_vio_sys_init(ot_vi_vpss_mode_type mode_type, ot_vi_video_mode video_mode,
    td_u32 yuv_cnt, td_u32 raw_cnt)
{
    td_s32 ret;
    ot_size size;
    ot_vb_cfg vb_cfg;
    td_u32 supplement_config;
    /* VB sized for the largest sensor (OS08A20 3840x2160) */
    sample_sns_type sns_type = SENSOR0_TYPE;

    sample_comm_vi_get_size_by_sns_type(sns_type, &size);
    sample_vi_get_default_vb_config(&size, &vb_cfg, video_mode, yuv_cnt, raw_cnt);
    printf("yuv_cnt:%d, raw_cnt:%d\n", yuv_cnt, raw_cnt);

    supplement_config = OT_VB_SUPPLEMENT_BNR_MOT_MASK;
    ret = sample_comm_sys_init_with_vb_supplement(&vb_cfg, supplement_config);
    if (ret != TD_SUCCESS) {
        return TD_FAILURE;
    }

    ret = sample_comm_vi_set_vi_vpss_mode(mode_type, video_mode);
    if (ret != TD_SUCCESS) {
        return TD_FAILURE;
    }
    printf("system init success\n");
    return TD_SUCCESS;
}

static td_s32 sample_vio_scene_auto_start(td_void)
{
    td_s32 ret;
    td_s32 choice = 0;
    ot_scene_video_mode video_mode;

    ret = ot_scene_create_param(SCENE_PARAM_PATH, &g_scene_param, &video_mode);
    if (ret != TD_SUCCESS) {
        printf("ot_scene_create_param failed\n");
        return TD_FAILURE;
    }

    ret = ot_scene_init(&g_scene_param);
    if (ret != TD_SUCCESS) {
        printf("ot_scene_init failed\n");
        return TD_FAILURE;
    }

    ot_scenecomm_expr_true_return(choice >= SCENE_MAX_VIDEOMODE, TD_FAILURE);

    ret = ot_scene_set_scene_mode(&(video_mode.video_mode[choice]));
    if (ret != TD_SUCCESS) {
        printf("ot_scene_set_scene_mode failed\n");
        return TD_FAILURE;
    }

    ret = ot_scene_pause(TD_FALSE);
    if (ret != TD_SUCCESS) {
        printf("ot_scene_pause failed\n");
        return TD_FAILURE;
    }

    printf("scene auto started\n");
    return TD_SUCCESS;
}

static td_void sample_vio_scene_auto_stop(td_void)
{
    td_s32 ret = ot_scene_deinit();
    if (ret != TD_SUCCESS) {
        printf("ot_scene_deinit failed\n");
    }
}

static td_s32 sample_vio_one_sensor0_and_dtof0(int i2c_num, td_char *server_ip)
{
    td_s32 ret;
    int i2c_bus_num;
    ot_vi_vpss_mode_type mode_type  = OT_VI_OFFLINE_VPSS_OFFLINE;
    ot_vi_video_mode     video_mode = OT_VI_VIDEO_MODE_NORM;
    ot_vi_pipe vi_pipe[2] = {0, 1};
    const ot_vi_chn  vi_chn   = 0;
    ot_vpss_grp vpss_grp[1]   = {0};
    const td_u32 grp_num      = 1;
    const ot_vpss_chn vpss_chn = 0;
    sample_vi_cfg vi_cfg[2];
    sample_sns_type sns_type;
    ot_size in_size;
    td_bool dtof_vi_started = TD_FALSE;
    td_bool dtof_sensor_registered = TD_FALSE;
    td_bool dtof_sensor_inited = TD_FALSE;
    td_bool dtof_dump_started = TD_FALSE;

    STEP_LOG("enter sample_vio_one_sensor0_and_dtof0 i2c_num=%d server_ip=%s", i2c_num, server_ip);
    ret = sample_vio_sys_init(mode_type, video_mode, 2, VB_LINEAR_RAW_CNT);
    STEP_LOG("sample_vio_sys_init ret=0x%x", ret);
    if (ret != TD_SUCCESS) {
        goto sys_init_failed;
    }

#if SUPPORT_RGB
    /* Camera: OS08A20 on sensor0, i2c_bus=i2c_num (5 when sns_num=1) */
    sns_type    = SENSOR0_TYPE;
    i2c_bus_num = i2c_num;
    sample_vi_get_one_sensor_vi_cfg_os08a20(sns_type, &vi_cfg[0], i2c_bus_num);
    ret = sample_vio_start_multi_vi_vpss_sensor_type(&vi_cfg[0], vpss_grp, 1, grp_num, sns_type);
    if (ret != TD_SUCCESS) {
        goto start_vi_vpss_failed;
    }

    sample_comm_vi_get_size_by_sns_type(sns_type, &in_size);
    printf("camera size width:%d, height:%d\n", in_size.width, in_size.height);
    ret = sample_vio_start_venc_and_vo(vpss_grp, grp_num, &in_size);
    if (ret != TD_SUCCESS) {
        goto start_venc_and_vo_failed;
    }

    ret = sample_vio_scene_auto_start();
    if (ret != TD_SUCCESS) {
        printf("warning: scene auto start failed, ISP running with defaults\n");
        /* non-fatal: camera still works without scene auto */
    }
#endif

#if SUPPORT_DTOF
    /* dToF: GS1860 on sensor2, i2c_bus=i2c_num-1 (4 when sns_num=1) */
    sns_type    = SENSOR1_TYPE;
    i2c_bus_num = i2c_num - 1;

    ret = gs1860_read_ini_file("./gs1860_register.ini");
    STEP_LOG("gs1860_read_ini_file ret=0x%x", ret);
    if (ret != TD_SUCCESS) {
        printf("gs1860_read_ini_file failed\n");
        goto EXIT;
    }

    ot_vi_dev vi_dev = 2;

    sample_vi_get_one_dtof_vi_cfg_gs1860(sns_type, &vi_cfg[1], i2c_bus_num);
    STEP_LOG("after sample_vi_get_one_dtof_vi_cfg_gs1860");
    ret = sample_comm_vi_start_vi(&vi_cfg[1]);
    STEP_LOG("sample_comm_vi_start_vi dtof ret=0x%x", ret);
    if (ret != TD_SUCCESS) {
        printf("dtof vi start failed\n");
        goto EXIT;
    }
    dtof_vi_started = TD_TRUE;

#ifdef DTOF_MANUAL_SENSOR_INIT
    ret = sample_comm_isp_sensor_regiter_callback(vi_pipe[1], sns_type);
    STEP_LOG("sample_comm_isp_sensor_regiter_callback dtof ret=0x%x", ret);
    if (ret != TD_SUCCESS) {
        printf("dtof register sns callback failed\n");
        goto EXIT;
    }
    dtof_sensor_registered = TD_TRUE;

    ret = sample_comm_isp_bind_sns(vi_pipe[1], sns_type, (td_s8)i2c_bus_num);
    STEP_LOG("sample_comm_isp_bind_sns dtof bus=%d ret=0x%x", i2c_bus_num, ret);
    if (ret != TD_SUCCESS) {
        printf("dtof bind sns bus failed\n");
        goto EXIT;
    }

    gs1860_init(vi_pipe[1]);
    dtof_sensor_inited = TD_TRUE;
    STEP_LOG("gs1860_init dtof pipe=%d done", vi_pipe[1]);
#endif

    ret = dtof_init(vi_pipe[1], server_ip);
    STEP_LOG("dtof_init ret=0x%x", ret);
    if (ret != TD_SUCCESS) {
        printf("dtof_init failed\n");
        goto EXIT;
    }

    ret = vi_bayerdump(server_ip, vi_pipe[1], vi_dev);
    STEP_LOG("vi_bayerdump ret=0x%x", ret);
    if (ret != TD_SUCCESS) {
        printf("vi_bayerdump failed: 0x%x\n", ret);
        goto EXIT;
    }
    dtof_dump_started = TD_TRUE;
#endif

    sample_get_char();

EXIT:
#if SUPPORT_RGB
    sample_vio_scene_auto_stop();
    sample_vio_stop_venc_and_vo(vpss_grp, grp_num);
#endif
#if SUPPORT_DTOF
    if (dtof_dump_started == TD_TRUE) {
        dtof_deinit();
    }
    if (dtof_sensor_inited == TD_TRUE) {
        gs1860_exit(vi_pipe[1]);
    }
    if (dtof_sensor_registered == TD_TRUE) {
        sample_comm_isp_sensor_unregiter_callback(vi_pipe[1]);
    }
#endif

start_venc_and_vo_failed:
#if SUPPORT_RGB
    sample_vio_stop_vpss(vpss_grp[0]);
    sample_comm_vi_un_bind_vpss(vi_cfg[0].bind_pipe.pipe_id[0], vi_chn, vpss_grp[0], vpss_chn);
    sample_comm_vi_stop_vi(&vi_cfg[0]);
#endif
#if SUPPORT_DTOF
    if (dtof_vi_started == TD_TRUE) {
        sample_comm_vi_stop_vi(&vi_cfg[1]);
    }
#endif

start_vi_vpss_failed:
    sample_comm_sys_exit();
sys_init_failed:
    return ret;
}

static td_void sample_vio_usage(const char *prog)
{
    printf("Usage: %s <snsnum> <serverip>\n", prog);
    printf("  eg: ./%s 1 192.168.137.100\n", prog);
    printf("  snsnum=1 -> camera i2c_bus=5, dtof i2c_bus=4\n");
}

int main(int argc, char *argv[])
{
    td_s32 ret;
    td_s32 sns_num = 0;
    td_char server_ip[64] = {0};

    setvbuf(stdout, NULL, _IONBF, 0);
    setvbuf(stderr, NULL, _IONBF, 0);
    STEP_LOG("main argc=%d", argc);
    if (argc < 3) {
        sample_vio_usage(argv[0]);
        return TD_FAILURE;
    }

    sns_num = argv[1][0] - '0';
    sprintf_s(server_ip, sizeof(server_ip), "%s", argv[2]);

    sigint_handler(sample_vio_handlesig);
    printf("starting OS08A20 camera + GS1860 dToF\n");
    STEP_LOG("call sample_vio_one_sensor0_and_dtof0 sns_num=%d i2c_bus=%d server_ip=%s",
        sns_num, sns_info[sns_num].i2c_bus, server_ip);
    ret = sample_vio_one_sensor0_and_dtof0(sns_info[sns_num].i2c_bus, server_ip);
    STEP_LOG("main ret=0x%x", ret);
    return ret;
}
