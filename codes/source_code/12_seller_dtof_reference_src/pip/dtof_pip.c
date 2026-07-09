#include "dtof/DataProc.h"

#include "dtof_pip.h"
#include "colormap_lut.h"

#define OT_SAMPLE_IVE_QUERY_SLEEP   100

td_s32 ive_comm_dma_frame_ex_roi_offset(ot_svp_src_img *src, ot_video_frame_info *frame_info,
    td_bool is_instant,
    td_u32 roi_x, td_u32 roi_y, td_u32 roi_w, td_u32 roi_h,
    td_u32 dst_x, td_u32 dst_y)
{
    td_s32 ret = OT_ERR_IVE_NULL_PTR;
    ot_ive_handle handle;
    ot_svp_src_data src_data;
    ot_svp_dst_data dst_data;
    ot_ive_dma_ctrl ctrl = { OT_IVE_DMA_MODE_DIRECT_COPY, 0, 0, 0, 0 };
    td_bool is_finish = TD_FALSE;
    td_bool is_block = TD_TRUE;

    td_u32 dst_w = frame_info->video_frame.width;
    td_u32 dst_h = frame_info->video_frame.height;
    td_u32 src_w = src->width;
    td_u32 src_h = src->height;

    // printf("src wxh: %d, %d\n", src_w, src_h);
    // printf("dst wxh: %d, %d\n", dst_w, dst_h);

    if (roi_x + roi_w > src_w || roi_y + roi_h > src_h) {
        return OT_ERR_IVE_ILLEGAL_PARAM;
    }
    if (dst_x + roi_w  > dst_w || dst_y + roi_h > dst_h) {
        return OT_ERR_IVE_ILLEGAL_PARAM;
    }

    sample_svp_check_exps_return(src == TD_NULL, ret, SAMPLE_SVP_ERR_LEVEL_ERROR, "src can't be null\n");
    sample_svp_check_exps_return(frame_info == TD_NULL, ret, SAMPLE_SVP_ERR_LEVEL_ERROR, "frame_info can't be null\n");
    sample_svp_check_exps_return(src->virt_addr == 0, ret, SAMPLE_SVP_ERR_LEVEL_ERROR, "src->virt_addr can't be 0\n");
    sample_svp_check_exps_return(src->phys_addr == 0, ret, SAMPLE_SVP_ERR_LEVEL_ERROR, "src->phys_addr can't be 0\n");
    sample_svp_check_exps_return(frame_info->video_frame.virt_addr == TD_NULL, ret, SAMPLE_SVP_ERR_LEVEL_ERROR,
        "frame_info->video_frame.virt_addr can't be null\n");
    ret = OT_ERR_IVE_ILLEGAL_PARAM;
    sample_svp_check_exps_return(frame_info->video_frame.phys_addr == 0, ret, SAMPLE_SVP_ERR_LEVEL_ERROR,
        "frame_info->video_frame.phys_addr can't be 0\n");

    src_data.virt_addr = (td_u64)src->virt_addr[0] + roi_y * src->stride[0] + roi_x;
    src_data.phys_addr = src->phys_addr[0] + roi_y * src->stride[0] + roi_x;
    src_data.width     = roi_w;
    src_data.height    = roi_h;
    src_data.stride    = src->stride[0];

    dst_data.virt_addr = (td_u64)frame_info->video_frame.virt_addr[0] + dst_y * frame_info->video_frame.stride[0] + dst_x;
    dst_data.phys_addr = frame_info->video_frame.phys_addr[0] + dst_y * frame_info->video_frame.stride[0] + dst_x;
    dst_data.width     = roi_w;
    dst_data.height    = roi_h;
    dst_data.stride    = frame_info->video_frame.stride[0];

    ret = ss_mpi_ive_dma(&handle, &src_data, &dst_data, &ctrl, is_instant);
    sample_svp_check_exps_return(ret != TD_SUCCESS, ret, SAMPLE_SVP_ERR_LEVEL_ERROR,
        "Error(%#x), ss_mpi_ive_dma Y plane failed!\n", ret);

    if (is_instant == TD_TRUE) {
        ret = ss_mpi_ive_query(handle, &is_finish, is_block);
        while (ret == OT_ERR_IVE_QUERY_TIMEOUT) {
            usleep(OT_SAMPLE_IVE_QUERY_SLEEP);
            ret = ss_mpi_ive_query(handle, &is_finish, is_block);
        }
        sample_svp_check_exps_return(ret != TD_SUCCESS, ret, SAMPLE_SVP_ERR_LEVEL_ERROR,
            "Error(%#x), ss_mpi_ive_query Y plane failed!\n", ret);
    }

    src_data.virt_addr = (td_u64)src->virt_addr[1] + (roi_y/2) * src->stride[1] + roi_x;
    src_data.phys_addr = src->phys_addr[1] + (roi_y/2) * src->stride[1] + roi_x;
    src_data.width     = roi_w;
    src_data.height    = roi_h / 2;
    src_data.stride    = src->stride[1];

    dst_data.virt_addr = (td_u64)frame_info->video_frame.virt_addr[1] + (dst_y/2) * frame_info->video_frame.stride[1] + dst_x;
    dst_data.phys_addr = frame_info->video_frame.phys_addr[1] + (dst_y/2) * frame_info->video_frame.stride[1] + dst_x;
    dst_data.width     = roi_w;
    dst_data.height    = roi_h / 2;
    dst_data.stride    = frame_info->video_frame.stride[1];

    ret = ss_mpi_ive_dma(&handle, &src_data, &dst_data, &ctrl, is_instant);
    sample_svp_check_exps_return(ret != TD_SUCCESS, ret, SAMPLE_SVP_ERR_LEVEL_ERROR,
        "Error(%#x), ss_mpi_ive_dma UV plane failed!\n", ret);

    if (is_instant == TD_TRUE) {
        ret = ss_mpi_ive_query(handle, &is_finish, is_block);
        while (ret == OT_ERR_IVE_QUERY_TIMEOUT) {
            usleep(OT_SAMPLE_IVE_QUERY_SLEEP);
            ret = ss_mpi_ive_query(handle, &is_finish, is_block);
        }
        sample_svp_check_exps_return(ret != TD_SUCCESS, ret, SAMPLE_SVP_ERR_LEVEL_ERROR,
            "Error(%#x), ss_mpi_ive_query UV plane failed!\n", ret);
    }

    return TD_SUCCESS;
}

static td_s32 sample_ive_proc_merge_bgr_planar(ot_svp_img *r_img, ot_svp_img *g_img, ot_svp_img *b_img, ot_svp_img *rgb_img,
    td_bool is_instant)
{
    td_s32 ret = TD_SUCCESS;
    ot_ive_handle handle;
    ot_svp_src_data src_data;
    ot_svp_dst_data dst_data;
    ot_ive_dma_ctrl ctrl = { OT_IVE_DMA_MODE_DIRECT_COPY, 0, 0, 0, 0 };
    td_bool is_finish = TD_FALSE;
    td_bool is_block  = TD_TRUE;

    sample_svp_check_exps_return(r_img == TD_NULL || g_img == TD_NULL || b_img == TD_NULL,
                                 OT_ERR_IVE_NULL_PTR, SAMPLE_SVP_ERR_LEVEL_ERROR, "Input img null\n");
    sample_svp_check_exps_return(rgb_img == TD_NULL, OT_ERR_IVE_NULL_PTR, SAMPLE_SVP_ERR_LEVEL_ERROR, "Output img null\n");

    td_u32 width  = r_img->width;
    td_u32 height = r_img->height;

    src_data.virt_addr = r_img->virt_addr[0];
    src_data.phys_addr = r_img->phys_addr[0];
    src_data.width     = width;
    src_data.height    = height;
    src_data.stride    = r_img->stride[0];

    dst_data.virt_addr = rgb_img->virt_addr[0];
    dst_data.phys_addr = rgb_img->phys_addr[0];
    dst_data.width     = width;
    dst_data.height    = height;
    dst_data.stride    = rgb_img->stride[0];

    ret = ss_mpi_ive_dma(&handle, &src_data, &dst_data, &ctrl, is_instant);
    sample_svp_check_exps_return(ret != TD_SUCCESS, ret, SAMPLE_SVP_ERR_LEVEL_ERROR, "DMA R plane failed\n");

    if (is_instant == TD_TRUE) {
        ret = ss_mpi_ive_query(handle, &is_finish, is_block);
        while (ret == OT_ERR_IVE_QUERY_TIMEOUT) {
            usleep(OT_SAMPLE_IVE_QUERY_SLEEP);
            ret = ss_mpi_ive_query(handle, &is_finish, is_block);
        }
        sample_svp_check_exps_return(ret != TD_SUCCESS, ret, SAMPLE_SVP_ERR_LEVEL_ERROR,
            "Error(%#x), ss_mpi_ive_query UV plane failed!\n", ret);
    }

    src_data.virt_addr = g_img->virt_addr[0];
    src_data.phys_addr = g_img->phys_addr[0];
    src_data.width     = width;
    src_data.height    = height;
    src_data.stride    = g_img->stride[0];

    dst_data.virt_addr = rgb_img->virt_addr[1];
    dst_data.phys_addr = rgb_img->phys_addr[1];
    dst_data.width     = width;
    dst_data.height    = height;
    dst_data.stride    = rgb_img->stride[1];

    ret = ss_mpi_ive_dma(&handle, &src_data, &dst_data, &ctrl, is_instant);
    sample_svp_check_exps_return(ret != TD_SUCCESS, ret, SAMPLE_SVP_ERR_LEVEL_ERROR, "DMA G plane failed\n");

    if (is_instant == TD_TRUE) {
        ret = ss_mpi_ive_query(handle, &is_finish, is_block);
        while (ret == OT_ERR_IVE_QUERY_TIMEOUT) {
            usleep(OT_SAMPLE_IVE_QUERY_SLEEP);
            ret = ss_mpi_ive_query(handle, &is_finish, is_block);
        }
        sample_svp_check_exps_return(ret != TD_SUCCESS, ret, SAMPLE_SVP_ERR_LEVEL_ERROR,
            "Error(%#x), ss_mpi_ive_query UV plane failed!\n", ret);
    }

    src_data.virt_addr = b_img->virt_addr[0];
    src_data.phys_addr = b_img->phys_addr[0];
    src_data.width     = width;
    src_data.height    = height;
    src_data.stride    = b_img->stride[0];

    dst_data.virt_addr = rgb_img->virt_addr[2];
    dst_data.phys_addr = rgb_img->phys_addr[2];
    dst_data.width     = width;
    dst_data.height    = height;
    dst_data.stride    = rgb_img->stride[2];

    ret = ss_mpi_ive_dma(&handle, &src_data, &dst_data, &ctrl, is_instant);
    sample_svp_check_exps_return(ret != TD_SUCCESS, ret, SAMPLE_SVP_ERR_LEVEL_ERROR, "DMA B plane failed\n");

    if (is_instant == TD_TRUE) {
        ret = ss_mpi_ive_query(handle, &is_finish, is_block);
        while (ret == OT_ERR_IVE_QUERY_TIMEOUT) {
            usleep(OT_SAMPLE_IVE_QUERY_SLEEP);
            ret = ss_mpi_ive_query(handle, &is_finish, is_block);
        }
        sample_svp_check_exps_return(ret != TD_SUCCESS, ret, SAMPLE_SVP_ERR_LEVEL_ERROR,
            "Error(%#x), ss_mpi_ive_query UV plane failed!\n", ret);
    }

    return TD_SUCCESS;
}

td_void dtof_ive_proc_uninit(dtof_ive_proc_info *ive_proc_info)
{
    sample_svp_mmz_free(ive_proc_info->depth_img_U16C1.phys_addr[0], ive_proc_info->depth_img_U16C1.virt_addr[0]);
    sample_svp_mmz_free(ive_proc_info->depth_img_U8C1.phys_addr[0], ive_proc_info->depth_img_U8C1.virt_addr[0]);

    sample_svp_mmz_free(ive_proc_info->b_img.phys_addr[0], ive_proc_info->b_img.virt_addr[0]);
    sample_svp_mmz_free(ive_proc_info->g_img.phys_addr[0], ive_proc_info->g_img.virt_addr[0]);
    sample_svp_mmz_free(ive_proc_info->r_img.phys_addr[0], ive_proc_info->r_img.virt_addr[0]);

    sample_svp_mmz_free(ive_proc_info->lut_map_b.phys_addr, ive_proc_info->lut_map_b.virt_addr);
    sample_svp_mmz_free(ive_proc_info->lut_map_g.phys_addr, ive_proc_info->lut_map_g.virt_addr);
    sample_svp_mmz_free(ive_proc_info->lut_map_r.phys_addr, ive_proc_info->lut_map_r.virt_addr);

    sample_svp_mmz_free(ive_proc_info->depth_img_color.phys_addr[0], ive_proc_info->depth_img_color.virt_addr[0]);

    sample_svp_mmz_free(ive_proc_info->scale_mem.phys_addr, ive_proc_info->scale_mem.virt_addr);
    sample_svp_mmz_free(ive_proc_info->depth_img_color_scale.phys_addr[0], ive_proc_info->depth_img_color_scale.virt_addr[0]);

    sample_svp_mmz_free(ive_proc_info->depth_dst_img.phys_addr[0], ive_proc_info->depth_dst_img.virt_addr[0]);
}

td_s32 dtof_ive_proc_init(dtof_ive_proc_info *ive_proc_info, td_u32 width, td_u32 height)
{
    td_s32 ret;
    td_u32 scale_width, scale_height;

    ive_proc_info->scale = 16;

    scale_width = width * ive_proc_info->scale;
    scale_height = height * ive_proc_info->scale;

    //DTOF U16C1深度图像
    ret = sample_common_ive_create_image(&ive_proc_info->depth_img_U16C1, OT_SVP_IMG_TYPE_U16C1, width, height);
    sample_svp_check_exps_return(ret != TD_SUCCESS, ret, SAMPLE_SVP_ERR_LEVEL_ERROR,
        "Error(%#x),Create depth_img_U16C1 image failed!\n", ret);

    //DTOF U16C1->U8C1归一化图像
    ret = sample_common_ive_create_image(&ive_proc_info->depth_img_U8C1, OT_SVP_IMG_TYPE_U8C1, width, height);
    sample_svp_check_exps_return(ret != TD_SUCCESS, ret, SAMPLE_SVP_ERR_LEVEL_ERROR,
        "Error(%#x),Create depth_img_U8C1 image failed!\n", ret);

    ret = sample_common_ive_create_image(&ive_proc_info->b_img, OT_SVP_IMG_TYPE_U8C1, width, height);
    sample_svp_check_exps_return(ret != TD_SUCCESS, ret, SAMPLE_SVP_ERR_LEVEL_ERROR,
        "Error(%#x),Create b_img image failed!\n", ret);

    ret = sample_common_ive_create_image(&ive_proc_info->g_img, OT_SVP_IMG_TYPE_U8C1, width, height);
    sample_svp_check_exps_return(ret != TD_SUCCESS, ret, SAMPLE_SVP_ERR_LEVEL_ERROR,
        "Error(%#x),Create g_img image failed!\n", ret);

    ret = sample_common_ive_create_image(&ive_proc_info->r_img, OT_SVP_IMG_TYPE_U8C1, width, height);
    sample_svp_check_exps_return(ret != TD_SUCCESS, ret, SAMPLE_SVP_ERR_LEVEL_ERROR,
        "Error(%#x),Create r_img image failed!\n", ret);

    ret = sample_common_ive_create_mem_info(&ive_proc_info->lut_map_b, 256);
    sample_svp_check_exps_return(ret != TD_SUCCESS, ret, SAMPLE_SVP_ERR_LEVEL_ERROR,
        "Error,create stack mem_info lut_map_b failed!\n");

    ret = sample_common_ive_create_mem_info(&ive_proc_info->lut_map_g, 256);
    sample_svp_check_exps_return(ret != TD_SUCCESS, ret, SAMPLE_SVP_ERR_LEVEL_ERROR,
        "Error,create stack mem_info lut_map_g failed!\n");

    ret = sample_common_ive_create_mem_info(&ive_proc_info->lut_map_r, 256);
    sample_svp_check_exps_return(ret != TD_SUCCESS, ret, SAMPLE_SVP_ERR_LEVEL_ERROR,
        "Error,create stack mem_info lut_map_r failed!\n");

    //DTOF 伪彩深度RGB图像
    ret = sample_common_ive_create_image(&ive_proc_info->depth_img_color, OT_SVP_IMG_TYPE_U8C3_PLANAR, width, height);
    sample_svp_check_exps_return(ret != TD_SUCCESS, ret, SAMPLE_SVP_ERR_LEVEL_ERROR,
        "Error(%#x),Create depth_img_color image failed!\n", ret);

    //缩放辅助内存
    ret = sample_common_ive_create_mem_info(&ive_proc_info->scale_mem, 49); //ctrl->mem 内存至少需要 25*U8C1_NUM + 49 * (ctrl->num – U8C1_NUM)字节
    sample_svp_check_exps_return(ret != TD_SUCCESS, ret, SAMPLE_SVP_ERR_LEVEL_ERROR,
        "Error,create stack mem_info scale_mem failed!\n");

    //DTOF 伪彩深度RGB放大的图像
    ret = sample_common_ive_create_image(&ive_proc_info->depth_img_color_scale, OT_SVP_IMG_TYPE_U8C3_PLANAR, scale_width, scale_height);
    sample_svp_check_exps_return(ret != TD_SUCCESS, ret, SAMPLE_SVP_ERR_LEVEL_ERROR,
        "Error(%#x),Create depth_img_color_scale image failed!\n", ret);

    //DTOF 伪彩深度YUV图像
    ret = sample_common_ive_create_image(&ive_proc_info->depth_dst_img, OT_SVP_IMG_TYPE_YUV420SP, scale_width, scale_height);
    sample_svp_check_exps_return(ret != TD_SUCCESS, ret, SAMPLE_SVP_ERR_LEVEL_ERROR,
        "Error(%#x),Create depth_dst_img image failed!\n", ret);

     return TD_SUCCESS;
}

static td_s32 dtof_query_task(ot_ive_handle handle)
{
    td_s32 ret;
    td_bool is_block = TD_TRUE;
    td_bool is_finish = TD_FALSE;

    ret = ss_mpi_ive_query(handle, &is_finish, is_block);
    while (ret == OT_ERR_IVE_QUERY_TIMEOUT) {
        usleep(OT_SAMPLE_IVE_QUERY_SLEEP);
        ret = ss_mpi_ive_query(handle, &is_finish, is_block);
    }
    sample_svp_check_exps_return(ret != TD_SUCCESS, ret, SAMPLE_SVP_ERR_LEVEL_ERROR,
        "Error(%#x),ss_mpi_ive_query failed!\n", ret);

    return TD_SUCCESS;
}

static td_void dtof_set_ctrl_info(td_u16 max_val, ot_ive_16bit_to_8bit_ctrl *ctrl_16to8bit,
    ot_ive_map_ctrl *lut_map_ctrl,
    ot_svp_mem_info scale_mem, ot_ive_resize_ctrl *resize_ctrl,
    ot_ive_csc_ctrl *csc_ctrl)
{
    /* set 16bit_to_8bit ctrl info */
    ctrl_16to8bit->bias = 0;
    ctrl_16to8bit->mode = OT_IVE_16BIT_TO_8BIT_MODE_U16_TO_U8;
    ctrl_16to8bit->num = 255;
    ctrl_16to8bit->denominator = (max_val > 255) ? max_val : 255;

    /* set map ctrl info */
    lut_map_ctrl->mode = OT_IVE_MAP_MODE_U8;

    /* set resize ctrl info */
    resize_ctrl->mode = OT_IVE_RESIZE_MODE_LINEAR;
    resize_ctrl->num  = 1;
    resize_ctrl->mem  = scale_mem;

    /* set csc ctrl info */
    csc_ctrl->mode = OT_IVE_CSC_MODE_VIDEO_BT601_RGB_TO_YUV;
}

td_s32 dtof_convert_depth_to_colormap(DtofHandle* dtof_handle, dtof_ive_proc_info *ive_proc_info)
{
    td_s32 ret;
    ot_ive_handle ive_handle;
    ot_ive_16bit_to_8bit_ctrl ctrl_16to8bit;
    ot_ive_map_ctrl lut_map_ctrl;
    ot_ive_resize_ctrl resize_ctrl;
    ot_ive_csc_ctrl csc_ctrl;

    td_u16 *dst = (td_u16*)sample_svp_convert_addr_to_ptr(td_void*, ive_proc_info->depth_img_U16C1.virt_addr[0]);
    memset(dst, 0, PAD_WIDTH * PAD_HEIGHT * sizeof(td_u16));

    //DTOF 深度数据填充到64x64
    int x_offset = 0; //(PAD_WIDTH - WIDTH) / 2;
    int y_offset = 0; //(PAD_HEIGHT - HEIGHT) / 2;

    for (int y = 0; y < HEIGHT; y++) {
        memcpy(&dst[(y + y_offset) * PAD_WIDTH + x_offset],
            &dtof_handle->dtofOutput.distance[y * WIDTH],
            WIDTH * sizeof(unsigned short));
    }

    td_u16 max_val = 0;
    for (int y = 0; y < ive_proc_info->depth_img_U16C1.height; y++) {
        for (int x = 0; x < ive_proc_info->depth_img_U16C1.width; x++) {
            td_u16 v = dst[y * (ive_proc_info->depth_img_U16C1.stride[0]/2) + x];
            if (v > max_val) max_val = v;
        }
    }
    // printf("Max value = %u\n", max_val);

    dtof_set_ctrl_info(max_val, &ctrl_16to8bit, &lut_map_ctrl, ive_proc_info->scale_mem, &resize_ctrl, &csc_ctrl);

    ret = ss_mpi_ive_16bit_to_8bit(&ive_handle, &ive_proc_info->depth_img_U16C1, &ive_proc_info->depth_img_U8C1, &ctrl_16to8bit, TD_TRUE);
    sample_svp_check_exps_return(ret != TD_SUCCESS, ret, SAMPLE_SVP_ERR_LEVEL_ERROR,
        "Error(%#x),ss_mpi_ive_16bit_to_8bit failed!\n", ret);

    ret = dtof_query_task(ive_handle);

    memcpy(sample_svp_convert_addr_to_ptr(td_void *, ive_proc_info->lut_map_b.virt_addr), g_lut_jet[0], 256);
    ss_mpi_ive_map(&ive_handle, &ive_proc_info->depth_img_U8C1, &ive_proc_info->lut_map_b, &ive_proc_info->b_img, &lut_map_ctrl, TD_TRUE);

    ret = dtof_query_task(ive_handle);

    memcpy(sample_svp_convert_addr_to_ptr(td_void *, ive_proc_info->lut_map_g.virt_addr), g_lut_jet[1], 256);
    ss_mpi_ive_map(&ive_handle, &ive_proc_info->depth_img_U8C1, &ive_proc_info->lut_map_g, &ive_proc_info->g_img, &lut_map_ctrl, TD_TRUE);

    ret = dtof_query_task(ive_handle);

    memcpy(sample_svp_convert_addr_to_ptr(td_void *, ive_proc_info->lut_map_r.virt_addr), g_lut_jet[2], 256);
    ss_mpi_ive_map(&ive_handle, &ive_proc_info->depth_img_U8C1, &ive_proc_info->lut_map_r, &ive_proc_info->r_img, &lut_map_ctrl, TD_TRUE);

    ret = dtof_query_task(ive_handle);

    sample_ive_proc_merge_bgr_planar(&ive_proc_info->b_img, &ive_proc_info->g_img, &ive_proc_info->r_img, &ive_proc_info->depth_img_color, TD_TRUE);

    ret = ss_mpi_ive_resize(&ive_handle, &ive_proc_info->depth_img_color, &ive_proc_info->depth_img_color_scale, &resize_ctrl, TD_TRUE);
    sample_svp_check_exps_return(ret != TD_SUCCESS, ret, SAMPLE_SVP_ERR_LEVEL_ERROR,"ss mpi ive resize failed,Error(%#x)\n", ret);

    ret = dtof_query_task(ive_handle);

    ret = ss_mpi_ive_csc(&ive_handle, &ive_proc_info->depth_img_color_scale, &ive_proc_info->depth_dst_img, &csc_ctrl, TD_TRUE);
    sample_svp_check_exps_return(ret != TD_SUCCESS, ret, SAMPLE_SVP_ERR_LEVEL_ERROR,"ss mpi ive csc failed,Error(%#x)\n", ret);

    ret = dtof_query_task(ive_handle);

    return ret;
}

td_s32 dtof_overlay_colormap_to_frame(dtof_ive_proc_info *ive_proc_info, ot_video_frame_info *frame_info, td_u32 idx)
{
    td_s32 ret;

    td_u32 roi_x = 0; //((PAD_WIDTH - WIDTH) / 2) * ive_proc_info->scale;
    td_u32 roi_y = 0; //((PAD_HEIGHT - HEIGHT) / 2) * ive_proc_info->scale;

    td_u32 roi_w = WIDTH * ive_proc_info->scale;
    td_u32 roi_h = HEIGHT * ive_proc_info->scale;


    if (idx == 0) {
        td_u32 dst_x = 0;
        td_u32 dst_y = frame_info->video_frame.height - roi_h;

        ret = ive_comm_dma_frame_ex_roi_offset(&ive_proc_info->depth_dst_img, frame_info, TD_TRUE, roi_x, roi_y, roi_w, roi_h, dst_x, dst_y);  //左下角
    }  else if (idx == 1) {

        td_u32 dst_x = frame_info->video_frame.width - roi_w;
        td_u32 dst_y = frame_info->video_frame.height - roi_h;
        ret = ive_comm_dma_frame_ex_roi_offset(&ive_proc_info->depth_dst_img, frame_info, TD_TRUE, roi_x, roi_y, roi_w, roi_h, dst_x, dst_y);  //右下角
    }

    return ret;
}