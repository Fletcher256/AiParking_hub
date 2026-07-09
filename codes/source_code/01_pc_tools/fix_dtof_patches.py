#!/usr/bin/env python3
"""
Fix incorrect patches in sample_dtof.c:
1. Revert mode 0 (sample_dtof_one_sensor) VENC back to VO
2. Correctly apply VENC patch to mode 3 (sample_dtof_dtof_and_rgb)
   - Cleanup at start_dtof_failed: is already correct (has VENC stop)
   - Just need to declare venc_chn and replace VO start
"""

filepath = "/home/ebaina/ZZIP/SS928V100_dtof_build_source/src/dtof/sample_dtof.c"

with open(filepath, 'r') as f:
    content = f.read()

changed = False

# --- Fix 1: Revert mode 0 - restore VO (remove accidentally inserted VENC) ---
old1 = """    sample_comm_vi_get_size_by_sns_type(sns_type, &in_size);

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
    sample_comm_vpss_bind_venc(vpss_grp[0], vpss_chn, venc_chn[0]);

    sample_get_char();

    sample_dtof_stop_vo(vpss_grp, grp_num);

start_vo_failed:"""

new1 = """    sample_comm_vi_get_size_by_sns_type(sns_type, &in_size);
    ret = sample_dtof_start_vo(vpss_grp, grp_num, &in_size);
    if (ret != TD_SUCCESS) {
        goto start_vo_failed;
    }

    sample_get_char();

    sample_dtof_stop_vo(vpss_grp, grp_num);

start_vo_failed:"""

if old1 in content:
    content = content.replace(old1, new1, 1)
    print("Fix 1 OK: mode 0 reverted to VO")
    changed = True
else:
    print("Fix 1 SKIP: mode 0 VENC block not found (already reverted?)")

# --- Fix 2: Replace VO with VENC in mode 3 (sample_dtof_dtof_and_rgb) ---
# Mode 3 is uniquely identified by the //DTOF comment after VO start
old2 = """    sample_comm_vi_get_size_by_sns_type(sns_type, &in_size);
    ret = sample_dtof_start_vo(vpss_grp, grp_num, &in_size);
    if (ret != TD_SUCCESS) {
        goto start_vo_failed;
    }

    //DTOF
    sns_type = SENSOR2_TYPE;"""

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
    sample_comm_vpss_bind_venc(vpss_grp[0], vpss_chn, venc_chn[0]);

    //DTOF
    sns_type = SENSOR2_TYPE;"""

if old2 in content:
    content = content.replace(old2, new2, 1)
    print("Fix 2 OK: mode 3 VO replaced with VENC start")
    changed = True
else:
    print("Fix 2 SKIP: mode 3 VO marker not found (already patched?)")

if changed:
    with open(filepath, 'w') as f:
        f.write(content)
    print("File written successfully")
else:
    print("No changes made")
