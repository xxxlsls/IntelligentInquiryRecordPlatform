/**
 * BE-7 辅助材料存储接口（/materials）
 */
import { httpDownloadGet, httpGet, httpPost } from '@/api/request'
import request from '@/api/request'
import type { MaterialListResult, MaterialOut, MaterialType } from '@/types'

/** 上传辅助材料（multipart/form-data，拖拽上传） */
export async function uploadMaterial(sessionId: string, file: File, materialType: MaterialType) {
  const form = new FormData()
  form.append('file', file)
  form.append('material_type', materialType)
  return httpPost<MaterialOut>(`/materials/sessions/${sessionId}/upload`, form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

/** 列出会话辅助材料（材料抽屉） */
export function listMaterials(sessionId: string) {
  return httpGet<MaterialListResult>(`/materials/sessions/${sessionId}`)
}

/** 下载辅助材料 */
export function downloadMaterial(materialId: string, fileName: string) {
  return httpDownloadGet(`/materials/${materialId}/download`, fileName)
}

/** 删除辅助材料（软删除） */
export function deleteMaterial(materialId: string) {
  return request.delete(`/materials/${materialId}`)
}
