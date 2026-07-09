#ifdef __cplusplus
#if __cplusplus
extern "C" {
#endif
#endif

#include "sample_comm.h"

//UDP
td_s32 dtof_init(ot_vi_pipe vi_pipe, td_char* serverip);
td_void dtof_deinit(td_void);
td_s32 vi_bayerdump(ot_vi_pipe vi_pipe, td_s32 vi_dev);

//PIP
td_s32 dtof_pip_init(ot_vi_pipe vi_pipe[], td_s32 cnt);
td_void dtof_pip_deinit(td_s32 cnt);
td_s32 vi_bayerdump_pip(ot_vi_pipe vi_pipe[],  ot_vi_dev vi_dev[], td_s32 cnt, ot_vpss_grp vpss_grp, ot_vpss_chn vpss_chn);

#ifdef __cplusplus
#if __cplusplus
}
#endif
#endif