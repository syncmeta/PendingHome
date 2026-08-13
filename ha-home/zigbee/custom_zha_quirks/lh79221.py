"""LH79221 —— 借 IAS Zone 告警位上报按压的单键无线开关。

这只设备（IEEE `00:15:8d:00:05:4e:2f:5a`，OUI 是 Lumi/绿米）把自己报成
IAS Zone 安防传感器（device_type 0x0402、输入簇 0x0500），但它其实是个
按钮：按一下就发一帧 `status_change_notification(zone_status=Alarm_1)`。

问题在于它**发完就不管了**，从不主动清零。ZHA 把 zone_status 的 bit 0
映射成 `binary_sensor` 的 on，于是实体按一次亮起来之后就一直停在 `on`。
后续每一次按压发的还是 `Alarm_1`，值没变 → ZHA 干脆不写状态（连
`last_reported` 都不动）→ HA 这层完全看不见，自动化再也不会触发。

唯一会把它拨回 `off` 的，是设备每 ~10.4 分钟一次的心跳
（`zone_status=Test`，bit 8）。也就是说不装这个 quirk 的话，
**一个心跳周期内只有第一次按压有效**，实测连按八下只有第一下点得亮灯。

`MotionWithReset` 正好治这个：收到 Alarm_1（`args[0] & 3`）后起一个定时器，
`reset_s` 秒后自己补一条 zone_status=0 的 cluster 命令，把实体拨回 `off`。
这样每按一次都产生干净的 `off → on` 边沿。

## reset_s 为什么是 1

关键是它必须**短于两次真实按压的最小间隔**，否则挨得近的两下会被并成一下。

实测抓帧确认过按压是"一次一帧"、不是重传 —— ZCL 的 TSN 严格递增
（`0x66,67,68,69,6a,6b,6c,6d,6e,6f,70` 一串连着来，没有重号），
所以不用担心把同一次按压的重传拆成多次触发。观测到的最小人手间隔约 0.8 秒，
取 1 秒是留了点余量的折中。

要是用起来发现"快按两下只亮一次"，把 reset_s 调小即可；反过来要是发现
一下按出两次翻转，调大。

签名照抄自 zigbee.db 里这台设备的实际记录，别凭包装盒上的字改：

    endpoints_v15:  (endpoint 1, profile 260, device_type 1026)
    clusters_v15 :  in  [0, 3, 25, 1280]      out [0, 3, 4, 5, 25]
    Basic 0x0004 (manufacturer) = ''          ← 厂商字段是空串，不是缺失
    Basic 0x0005 (model)        = 'LH79221'

装在哪、怎么生效见同目录 README.md 的「Test 是心跳」一节。
"""

from zhaquirks import MotionWithReset
from zhaquirks.const import (
    DEVICE_TYPE,
    ENDPOINTS,
    INPUT_CLUSTERS,
    MODELS_INFO,
    OUTPUT_CLUSTERS,
    PROFILE_ID,
)
from zhaquirks.legacy import CustomDevice
from zigpy.profiles import zha
from zigpy.zcl.clusters.general import Basic, Groups, Identify, Ota, Scenes
from zigpy.zcl.clusters.security import IasZone


class LH79221ButtonCluster(MotionWithReset):
    """按一下报 Alarm_1，reset_s 秒后自动补一条清零，好让下一次按压有新边沿。"""

    reset_s: int = 1
    # 这只设备没有 occupancy 实体，不用往 occupancy_bus 上转发事件
    # （置 True 的话 CustomDevice 还得自己建 Bus，见 zhaquirks.konke）。
    send_occupancy_event: bool = False


class LH79221Button(CustomDevice):
    """把 LH79221 的 IAS Zone 换成会自动复位的版本。"""

    signature = {
        MODELS_INFO: [("", "LH79221")],
        ENDPOINTS: {
            1: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.IAS_ZONE,
                INPUT_CLUSTERS: [
                    Basic.cluster_id,
                    Identify.cluster_id,
                    Ota.cluster_id,
                    IasZone.cluster_id,
                ],
                OUTPUT_CLUSTERS: [
                    Basic.cluster_id,
                    Identify.cluster_id,
                    Groups.cluster_id,
                    Scenes.cluster_id,
                    Ota.cluster_id,
                ],
            }
        },
    }

    replacement = {
        ENDPOINTS: {
            1: {
                PROFILE_ID: zha.PROFILE_ID,
                DEVICE_TYPE: zha.DeviceType.IAS_ZONE,
                INPUT_CLUSTERS: [
                    Basic.cluster_id,
                    Identify.cluster_id,
                    Ota.cluster_id,
                    LH79221ButtonCluster,
                ],
                OUTPUT_CLUSTERS: [
                    Basic.cluster_id,
                    Identify.cluster_id,
                    Groups.cluster_id,
                    Scenes.cluster_id,
                    Ota.cluster_id,
                ],
            }
        }
    }
