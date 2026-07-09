#!/usr/bin/env python3
"""
Patch sample_dtof.c on the VM:
1. Add g_venc_chn_param static variable
2. Replace VO with VENC in sample_dtof_dtof_and_rgb (mode 3)
"""

filepath = "/home/ebaina/ZZIP/SS928V100_dtof_build_source/src/dtof/sample_dtof.c"

with open(filepath, 'r') as f:
    content = f.read()

changed = False

# --- Patch 1: Add g_venc_chn_param after g_vo_cfg ---
old1 = """    .compress_mode     = OT_COMPRESS_MODE_NONE,
};

static td_void sample_get_char"""

new1 = """    .compress_mode     = OT_COMPRESS_MODE_NONE,
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

static td_void sample_get_char"""

if old1 in content:
    content = content.replace(old1, new1, 1)
    print("Patch 1 OK: g_venc_chn_param added")
    changed = True
else:
    print("Patch 1 SKIP: marker not found (may already be patched)")

# --- Patch 2: Replace VO with VENC in sample_dtof_dtof_and_rgb ---
old2 = """    sample_comm_vi_get_size_by_sns_type(sns_type, &in_size);
    ret = sample_dtof_start_vo(vpss_grp, grp_num, &in_size);
    if (ret != TD_SUCCESS) {
        goto start_vo_failed;
    }"""

new2 = """    sample_comm_vi_get_size_by_sns_type(sns_type, &in_size);

    /* Replace VO with VENC for headless H.264 output */
    ot_venc_chn venc_chn[1] = {0};
    g_venc_chn_param.venc_size.width  = in_size.width;
    g_venc_chn_param.venc_size.height = in_size.height;
    g_venc_chn_param.size = sample_comm_sys_get_pic_enum(&in_size);
    ret = sample_comm_venc_start(venc_chn[0], &g_venc_chn_param);
    if (ret != TD_SUCCESS) {
        goto start_vo_failed;
    }
    ret = sample_comm_venc_start_get_stream(venc_chn, 1);
    if (ret != TD_SUCCESS) {
        sample_comm_venc_stop(venc_chn[0]);
        goto start_vo_failed;
    }
    sample_comm_vpss_bind_venc(vpss_grp[0], vpss_chn, venc_chn[0]);"""

if old2 in content:
    content = content.replace(old2, new2, 1)
    print("Patch 2 OK: VO replaced with VENC start")
    changed = True
else:
    print("Patch 2 SKIP: marker not found (may already be patched)")

# --- Patch 3: Replace stop_vo with VENC stop in cleanup ---
old3 = """start_dtof_failed:
    sample_dtof_stop_vo(vpss_grp, grp_num);
start_vo_failed:"""

new3 = """start_dtof_failed:
    /* Stop VENC (replaced VO) */
    sample_comm_vpss_un_bind_venc(vpss_grp[0], vpss_chn, venc_chn[0]);
    sample_comm_venc_stop_get_stream(1);
    sample_comm_venc_stop(venc_chn[0]);
start_vo_failed:"""

if old3 in content:
    content = content.replace(old3, new3, 1)
    print("Patch 3 OK: VO stop replaced with VENC stop")
    changed = True
else:
    print("Patch 3 SKIP: marker not found (may already be patched)")

if changed:
    with open(filepath, 'w') as f:
        f.write(content)
    print("File written successfully")
else:
    print("No changes made")
