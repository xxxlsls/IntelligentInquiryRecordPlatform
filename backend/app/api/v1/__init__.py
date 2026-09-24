"""
api.v1 包 · v1 版本接口路由

各路由模块对应需求文档 3.7 的 8 大后端模块：
- auth        BE-1 认证与权限（登录/登出/会话校验/权限查询）
- org         BE-1 组织机构与警员维护、机构树
- sessions    BE-2 笔录生命周期（会话 CRUD、阶段流转、问答编排、断点恢复）
- external    BE-3 外部系统集成（只读检索、字段回填）
- templates   BE-4 模板配置服务（模板 CRUD、问题库、动态加载）
- ai          BE-5 AI 研判推荐（模板推荐、研判建议、采纳）
- fiveflow    BE-6 五流要素分析引擎（覆盖度、缺口、要素定义）
- materials   BE-7 文件与存储（上传、列表、下载）
- documents   文书导出（预览、DOCX 生成下载）
- imports     BE-6 历史笔录解析导入
- audit       BE-8 审计监控（检索）
"""
