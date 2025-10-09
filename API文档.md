### ✅ **一、普通用户接口**

#### 1. 提交文章
- **URL**: `POST /post`
- **请求参数（JSON）**:
  ```json
  { "content": "你的文章内容" }
  ```
- **返回**:
  
  ```json
  { "id": 123, "status": "Pass" }  // 或 "Pending"（若需审核）
  ```
- **说明**：内容含违禁词则拒绝（403），空内容则报错（400）

---

#### 2. 点赞文章
- **URL**: `POST /up`
- **请求参数（JSON）**:
  ```json
  { "id": 123 }
  ```
- **返回**:
  ```json
  { "status": "OK" }
  ```

---

#### 3. 反对文章（踩）
- **URL**: `POST /down`
- **请求参数（JSON）**:
  ```json
  { "id": 123 }
  ```
- **返回**:
  ```json
  { "status": "OK" }
  ```

---

#### 4. 发布评论
- **URL**: `POST /comment`
- **请求参数（JSON）**:
  ```json
  {
    "content": "评论内容",
    "submission_id": 123,
    "parent_comment_id": 0,  // 回复父评论时填 ID
    "nickname": "昵称"       // 可为空，自动为“匿名用户”
  }
  ```
- **返回**:
  ```json
  { "id": 456, "status": "Pass" }
  ```
- **说明**：违禁词拒绝（403），无效文章或父评论 ID 返回对应错误码

---

#### 5. 上传图片
- **URL**: `POST /upload_pic`
- **请求参数**：
  - 表单字段：`file`（文件），支持 `.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`
- **返回**:
  ```json
  { "status": "OK", "url": "/img/240510_aBc12.png" }
  ```
- **限制**：文件大小 ≤10MB，格式正确

---

#### 6. 获取文章状态（是否通过审核）
- **URL**: `GET /get/post_state`
- **参数（query）**:
  - `id=123`
- **返回**:
  ```json
  { "status": "Approved" }     // 通过
  { "status": "Pending" }      // 待审核
  { "status": "Rejected" }     // 拒绝
  { "status": "Deleted or Not Found" } // 不存在
  ```

---

#### 7. 获取投诉状态
- **URL**: `GET /get/report_state`
- **参数（query）**:
  - `id=789`
- **返回**:
  ```json
  { "status": "Approved" }     // 已通过
  { "status": "Pending" }      // 待处理
  { "status": "Rejected" }     // 已拒绝
  ```

---

#### 8. 获取公开文章详情（仅通过审核的）
- **URL**: `GET /get/post_info`
- **参数（query）**:
  - `id=123`
- **返回**:
  ```json
  {
    "id": 123,
    "content": "文章内容",
    "created_at": "2024-05-10T12:00:00+00:00",
    "updated_at": "2024-05-10T12:00:00+00:00",
    "upvotes": 5,
    "downvotes": 1
  }
  ```

---

#### 9. 获取评论列表
- **URL**: `GET /get/comment`
- **参数（query）**:
  - `id=123`
- **返回**:
  ```json
  [
    {
      "id": 456,
      "nickname": "张三",
      "content": "这是一条评论",
      "parent_comment_id": 0,
      "upvotes": 2,
      "downvotes": 0,
      "created_at": "2024-05-10T12:05:00+00:00"
    }
  ]
  ```

---

#### 10. 获取最新10条文章列表（分页）
- **URL**: `GET /get/10_info`
- **参数（query）**:
  - `page=1`（可选，缺省为1）
- **返回**:
  ```json
  [
    {
      "id": 123,
      "content": "文章内容",
      "created_at": "2024-05-10T12:00:00+00:00",
      "updated_at": "2024-05-10T12:00:00+00:00",
      "status": "Pass"
    }
  ]
  ```

---

#### 11. 获取系统统计信息
- **URL**: `GET /get/statics`
- **返回**:
  ```json
  {
    "posts": 150,
    "comments": 300,
    "images": 80
  }
  ```

---

#### 12. 提交投诉
- **URL**: `POST /report`
- **请求参数（JSON）**:
  ```json
  {
    "id": 123,
    "title": "举报标题",
    "content": "举报原因"
  }
  ```
- **返回**:
  ```json
  { "id": 101, "status": "OK" }
  ```

---

### ✅ **二、管理后台接口（需要 Bearer Token）**

> **调用方式**：在请求头加上：
> ```
> Authorization: Bearer your_admin_token
> ```

#### 1. 查看文章详情（完整信息）
- **URL**: `GET /admin/get/post_info`
- **参数（query）**:
  - `id=123`
- **返回**：
  ```json
  {
    "id": 123,
    "content": "文章内容",
    "created_at": "2024-05-10T12:00:00+00:00",
    "updated_at": "2024-05-10T12:00:00+00:00",
    "status": "Pass",
    "upvotes": 5,
    "downvotes": 1
  }
  ```

---

#### 2. 审核文章：通过
- **URL**: `POST /admin/approve`
- **请求参数（JSON）**:
  ```json
  { "id": 123 }
  ```
- **返回**:
  ```json
  { "status": "OK" }
  ```

---

#### 3. 审核文章：拒绝
- **URL**: `POST /admin/disapprove`
- **请求参数（JSON）**:
  ```json
  { "id": 123 }
  ```
- **返回**:
  ```json
  { "status": "OK" }
  ```

---

#### 4. 重新审核文章（置为 Pending）
- **URL**: `POST /admin/reaudit`
- **请求参数（JSON）**:
  ```json
  { "id": 123 }
  ```
- **返回**:
  ```json
  { "status": "OK" }
  ```

---

#### 5. 删除文章（包括评论）
- **URL**: `POST /admin/del_post`
- **请求参数（JSON）**:
  ```json
  { "id": 123 }
  ```
- **返回**:
  ```json
  { "status": "OK" }
  ```

---

#### 6. 修改文章内容
- **URL**: `POST /admin/modify_post`
- **请求参数（JSON）**:
  ```json
  { "id": 123, "content": "新内容" }
  ```
- **返回**:
  ```json
  { "status": "OK" }
  ```

---

#### 7. 删除评论
- **URL**: `POST /admin/del_comment`
- **请求参数（JSON）**:
  ```json
  { "id": 456 }
  ```
- **返回**:
  ```json
  { "status": "OK" }
  ```

---

#### 8. 修改评论
- **URL**: `POST /admin/modify_comment`
- **请求参数（JSON）**:
  ```json
  {
    "id": 456,
    "content": "新内容",
    "parent_comment_id": 0,
    "nickname": "新昵称"
  }
  ```
- **返回**:
  ```json
  { "status": "OK" }
  ```

---

#### 9. 删除图片
- **URL**: `POST /admin/del_pic`
- **请求参数（JSON）**:
  ```json
  { "filename": "240510_aBc12.png" }
  ```
- **返回**:
  ```json
  { "status": "OK" }
  ```

---

#### 10. 管理投诉：通过
- **URL**: `POST /admin/approve_report`
- **请求参数（JSON）**:
  ```json
  { "id": 101 }
  ```
- **行为**：标记投诉为通过，并**删除对应文章及其所有评论**

---

#### 11. 管理投诉：拒绝
- **URL**: `POST /admin/reject_report`
- **请求参数（JSON）**:
  ```json
  { "id": 101 }
  ```
- **返回**:
  ```json
  { "status": "OK" }
  ```

---

#### 12. 开启/关闭审核功能
- **URL**: `POST /admin/need_audit`
- **请求参数（JSON）**:
  ```json
  { "need_audit": true }  // 或 false
  ```
- **返回**:
  ```json
  { "status": "OK" }
  ```

---

#### 13. 获取当前是否需审核
- **URL**: `GET /admin/get/need_audit`
- **返回**:
  ```json
  { "status": true }
  ```

---

#### 14. 获取待审核文章列表
- **URL**: `GET /admin/get/pending_posts`
- **返回**:
  ```json
  [
    {
      "id": 123,
      "content": "待审内容",
      "created_at": "2024-05-10T12:00:00+00:00",
      "updated_at": "2024-05-10T12:00:00+00:00",
      "status": "Pending"
    }
  ]
  ```

---

#### 15. 获取被拒绝文章
- **URL**: `GET /admin/get/reject_posts`
- **返回**：
  - 结构同上，仅状态为 "Deny"

---

#### 16. 获取所有图片链接（分页）
- **URL**: `GET /admin/get/pic_links`
- **参数（query）**:
  - `page=1`
- **返回**:
  ```json
  [
    "/img/240510_aBc12.png",
    "/img/240510_xYz34.jpg"
  ]
  ```

---

#### 17. 获取待处理投诉
- **URL**: `GET /admin/get/pending_reports`
- **返回**:
  ```json
  [
    {
      "id": 101,
      "submission_id": 123,
      "title": "举报标题",
      "content": "举报内容",
      "status": "Pending",
      "created_at": "2024-05-10T12:00:00+00:00"
    }
  ]
  ```

---

#### 18. 下载备份文件
- **URL**: `GET /admin/get/backup`
- **返回**：一个 `.zip` 文件，包含数据库和 `img/` 文件夹

---

#### 19. 恢复备份
- **URL**: `POST /admin/recover`
- **请求**：上传一个 `.zip` 备份文件（form-data）
- **返回**:
  ```json
  { "status": "OK" }
  ```
- **行为**：解压覆盖当前数据库和图片目录

---

### 🟩 总结说明

| 功能         | 接口路径              | 是否需要 Token | 说明                           |
| ------------ | --------------------- | -------------- | ------------------------------ |
| 提交文章     | `POST /post`          | 否             | 含违禁词或空则拒绝             |
| 点赞/踩      | `POST /up`, `/down`   | 否             | 仅需文章 ID                    |
| 发布评论     | `POST /comment`       | 否             | 有合规校验                     |
| 上传图片     | `POST /upload_pic`    | 否             | 仅支持特定格式                 |
| 获取文章状态 | `GET /get/post_state` | 否             | 无权限限制                     |
| 提交投诉     | `POST /report`        | 否             | 带文章 ID                      |
| 获取统计     | `GET /get/statics`    | 否             | 公开数据                       |
| 后台操作     | 所有 `/admin/...`     | ✅ 必须         | 使用 `Bearer your_admin_token` |

---

> ✅ 所有返回均为 JSON 格式，状态码 200/201 表示成功，其余为错误（如 400, 403, 404, 500）。
