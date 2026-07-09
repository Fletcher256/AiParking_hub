#ifndef DTOF_PIP_H
#define DTOF_PIP_H

#ifdef __cplusplus
extern "C" {
#endif

#include "sample_comm.h"
#include "sample_common_ive.h"

#define MAX_DTOF 2

#define WIDTH 40
#define HEIGHT 30

#define PAD_WIDTH 64
#define PAD_HEIGHT 64

#define BIN_NUM 64

#define SECOND_TO_MILLI_SECOND (1000 * 1000)
#define NANO_SECOND_TO_MILLI_SECOND 1000
#define MID_PIXEL (14 * 40 + 19)
#define VALID_DATA_NUM 3

#define DTOF_INI_FILE_PATH   "./dtof.ini"
#define DTOF_SPOT_FILE_PATH  "./spot_coor.bin"

typedef struct {
    ot_svp_img depth_img_U16C1;
    ot_svp_img depth_img_U8C1;

    ot_svp_img b_img, g_img, r_img;
    ot_svp_mem_info lut_map_b, lut_map_g, lut_map_r;
    ot_svp_img depth_img_color;

    td_s32 scale;
    ot_svp_mem_info scale_mem;
    ot_svp_img depth_img_color_scale;

    ot_svp_img depth_dst_img;

} dtof_ive_proc_info;

td_void dtof_ive_proc_uninit(dtof_ive_proc_info *ive_proc_info);
td_s32 dtof_ive_proc_init(dtof_ive_proc_info *ive_proc_info, td_u32 width, td_u32 height);

td_s32 dtof_convert_depth_to_colormap(DtofHandle* dtof_handle, dtof_ive_proc_info *ive_proc_info);

td_s32 dtof_overlay_colormap_to_frame(dtof_ive_proc_info *ive_proc_info, ot_video_frame_info *frame_info, td_u32 idx);

#ifdef __cplusplus
}
#endif
#endif