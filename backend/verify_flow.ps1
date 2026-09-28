# ============================================================
# 笔录制作业务闭环验证脚本（临时）
# 链路：建档 → 流转 → 选模板装配 → 新增问答 → 五流抽取 → AI研判
#       → 完成笔录 → 导出DOCX → 审计核查
# 覆盖模块：BE-2 / BE-4 / BE-5 / BE-6 / BE-7 / BE-8
# ============================================================
$ErrorActionPreference = "Stop"
$base = "http://127.0.0.1:8000/api/v1"

function Post-Json($url, $obj, $headers) {
    $json = if ($obj -is [string]) { $obj } else { $obj | ConvertTo-Json -Depth 6 }
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
    return Invoke-RestMethod -Uri $url -Method Post -Body $bytes -Headers $headers -ContentType "application/json; charset=utf-8"
}

# ---------- 登录办案民警 ----------
$login = Post-Json "$base/auth/login" @{ officer_no = "minjing"; password = "123456" } @{}
$h = @{ Authorization = "Bearer $($login.data.access_token)" }

# ---------- 1. 接报建档 (BE-2) ----------
$caseNo = "TEST-" + (Get-Date -Format "yyyyMMddHHmmss")
$sess = Post-Json "$base/sessions" @{
    case_no = $caseNo; case_category = "刷单返利"
    brief = "报案人称在网上参与刷单返利活动，被对方诱导多次转账充值共计五万元，随后无法提现察觉被骗。"
    reporter_name = "李某"; reporter_phone = "13800138000"
} $h
$sid = $sess.data.id
Write-Host "[BE-2] 建档成功 案件号=$caseNo 会话ID=$sid 阶段=$($sess.data.stage)" -ForegroundColor Cyan

# ---------- 2. 阶段流转 intake → templates (BE-2 状态机) ----------
$st = Post-Json "$base/sessions/$sid/stage" @{ target_stage = "templates" } $h
Write-Host "[BE-2] 阶段流转 → $($st.data.stage)"

# ---------- 3. 选模板装配大纲 (BE-4/BE-2) ----------
$tpl = Invoke-RestMethod -Uri "$base/templates?only_enabled=true" -Headers $h
$tplId = $tpl.data[0].id
$tplJson = ConvertTo-Json @($tplId)   # 数组body
$sel = Post-Json "$base/sessions/$sid/select-templates" $tplJson $h
Write-Host "[BE-4] 选定模板=$($tpl.data[0].name) 装配后阶段=$($sel.data.stage)"

# ---------- 4. 新增问答 (BE-2) ----------
$qa = Post-Json "$base/sessions/$sid/questions" @{
    chapter = "fraud_process"; question = "请描述你是如何接触到这个刷单返利平台的？"
    answer = "我在微信群看到广告，添加了对方的QQ，对方发来一个链接让我注册做任务。"
} $h
Write-Host "[BE-2] 新增问答成功 qa_id=$($qa.data.id) 章节=$($qa.data.chapter)"

# ---------- 5. 五流要素抽取 (BE-6) ----------
$ext = Post-Json "$base/fiveflow/sessions/$sid/extract" "{}" $h
Write-Host "[BE-6] 五流抽取完成 整体覆盖度=$($ext.data.overall_coverage)%"

# ---------- 6. AI 研判 (BE-5) ----------
$an = Post-Json "$base/ai/sessions/$sid/analyze" "{}" $h
Write-Host "[BE-5] AI研判完成 生成建议数=$($an.data.suggestions.Count) 涉诈类型=$($an.data.case_type_judgment)"

# ---------- 7. 完成笔录 (BE-2) ----------
$done = Invoke-RestMethod -Uri "$base/sessions/$sid/complete" -Method Post -Headers $h -ContentType "application/json"
Write-Host "[BE-2] 笔录完成 阶段=$($done.data.stage) 归档=$($done.data.is_archived)"

# ---------- 8. 导出 DOCX 文书 (BE-7) ----------
$expBody = [System.Text.Encoding]::UTF8.GetBytes((@{ include_fiveflow_table = $true; include_ai_report = $true } | ConvertTo-Json))
$outFile = ".\verify_output_record.docx"
$resp = Invoke-WebRequest -Uri "$base/documents/sessions/$sid/export" -Method Post -Body $expBody -Headers $h -ContentType "application/json; charset=utf-8" -OutFile $outFile -PassThru
$size = (Get-Item $outFile).Length
Write-Host "[BE-7] DOCX导出成功 文件大小=$size 字节 指纹=$($resp.Headers['X-Document-Fingerprint'])"

# ---------- 9. 审计核查 (BE-8) ----------
$audit = Invoke-RestMethod -Uri "$base/audit/logs?case_no=$caseNo" -Headers $h
Write-Host "[BE-8] 该案件审计记录数=$($audit.data.total)"
foreach ($log in $audit.data.items) {
    Write-Host "   - $($log.op_type) | $($log.description)"
}

Write-Host "`n== 业务闭环全部验证通过 ==" -ForegroundColor Green