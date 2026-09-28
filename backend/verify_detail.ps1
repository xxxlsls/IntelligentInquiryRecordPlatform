# ============================================================
# 补验脚本：用正确字段名核查 五流覆盖度(BE-6) / AI研判(BE-5) / 审计明细(BE-8)
# 针对 verify_flow.ps1 刚创建的会话（取台账中最近一条 completed 会话）
# ============================================================
$ErrorActionPreference = "Stop"
$base = "http://127.0.0.1:8000/api/v1"

function Post-Json($url, $obj, $headers) {
    $json = if ($obj -is [string]) { $obj } else { $obj | ConvertTo-Json -Depth 6 }
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
    return Invoke-RestMethod -Uri $url -Method Post -Body $bytes -Headers $headers -ContentType "application/json; charset=utf-8"
}

$login = Post-Json "$base/auth/login" @{ officer_no = "minjing"; password = "123456" } @{}
$h = @{ Authorization = "Bearer $($login.data.access_token)" }

# 取最近创建的会话
$list = Invoke-RestMethod -Uri "$base/sessions" -Headers $h
$s = $list.data | Sort-Object updated_at -Descending | Select-Object -First 1
$sid = $s.id
Write-Host "== 目标会话: 案件号=$($s.case_no) 阶段=$($s.stage) 进度=$($s.progress)% ==" -ForegroundColor Cyan

# ---------- BE-6 五流覆盖度（正确字段 coverage_pct / status） ----------
$cov = Invoke-RestMethod -Uri "$base/fiveflow/sessions/$sid/coverage" -Headers $h
Write-Host "[BE-6] 整体覆盖度=$($cov.data.overall_coverage)%"
foreach ($fl in $cov.data.flow_coverages) {
    Write-Host "   - $($fl.flow_label): 覆盖度=$($fl.coverage_pct)% 状态=$($fl.status) 核心缺口=$($fl.is_key_gap) 已收集$($fl.n_collected)/应收集$($fl.n_required)"
}
Write-Host "[BE-6] 重点缺口要素=$($cov.data.key_gap_elements -join ',')"
Write-Host "[BE-6] 已收集要素=$($cov.data.collected_elements -join ',')"

# ---------- BE-5 AI研判（正确字段 fraud_type / suggestions / key_gap_questions） ----------
$an = Post-Json "$base/ai/sessions/$sid/analyze" "{}" $h
Write-Host "[BE-5] 涉诈类型判定=$($an.data.fraud_type)"
Write-Host "[BE-5] 事实特征数=$($an.data.fact_features.Count) 侦查指引长度=$($an.data.investigation_guide.Length)"
Write-Host "[BE-5] 中栏建议数=$($an.data.suggestions.Count) 重点缺口追问数=$($an.data.key_gap_questions.Count)"
foreach ($sg in $an.data.suggestions) {
    Write-Host "   - [$($sg.suggestion_type)] $($sg.content)"
}

# ---------- BE-8 审计明细（正确路径 data.items） ----------
$audit = Invoke-RestMethod -Uri "$base/audit/logs?case_no=$($s.case_no)" -Headers $h
Write-Host "[BE-8] 案件审计记录数=$($audit.data.total)"
foreach ($log in $audit.data.items) {
    Write-Host "   - $($log.op_type) | 结果=$($log.op_result) | $($log.description)"
}

Write-Host "`n== 补验完成 ==" -ForegroundColor Green
