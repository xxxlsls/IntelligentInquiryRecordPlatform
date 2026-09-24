"""
组织机构与演示账号种子数据（对应 2.3.1 三级组织架构 / FR-3.1.3）

提供市局→分局→所队三级机构与三类角色演示账号，便于端到端演示与验收（AC-1）。
演示账号初始密码统一为 Admin@12345 / Officer@123 等（长度≥8，符合 FR-3.1.1）。
"""

# 组织机构：(name, code, level, parent_code, sort_order)
ORGS: list[tuple] = [
    ("某市公安局", "ORG_CITY", "city_bureau", None, 1),
    ("某市公安局某分局", "ORG_SUB_01", "sub_bureau", "ORG_CITY", 1),
    ("某分局反诈中心", "ORG_STATION_01", "station", "ORG_SUB_01", 1),
    ("某分局某派出所", "ORG_STATION_02", "station", "ORG_SUB_01", 2),
]

# 演示账号：(officer_no, name, role, org_code, plain_password, phone)
USERS: list[tuple] = [
    # 系统管理员（AC-1：三类角色登录）
    ("ADMIN001", "系统管理员", "admin", "ORG_CITY", "Admin@12345", "13800000001"),
    # 办案民警（不同所队，验证机构隔离 DR-2）
    ("P10001", "张警官", "case_officer", "ORG_STATION_01", "Officer@123", "13800000002"),
    ("P10002", "李警官", "case_officer", "ORG_STATION_02", "Officer@123", "13800000003"),
    # 反诈研判员（本机构只读）
    ("A20001", "王研判", "analyst", "ORG_SUB_01", "Analyst@123", "13800000004"),
]
