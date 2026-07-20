# Python Code Style

## 核心原則：效率優先，不是行數最少

寫 Python 時以**執行效率**為第一優先，不是把程式碼硬擠成最短。判斷標準是「計算某份資料或查詢某筆記錄時，是否用了最少的計算量/查詢次數得到答案」，而不是「這段程式碼看起來夠不夠精簡」。兩者常常一致，但衝突時效率優先。

具體來說：
- **避免重複計算**：同一個值在函式裡若會用到多次，算一次存起來，不要每次用到就重算一次。
- **避免 N+1 查詢**：迴圈裡對資料庫或外部 API 一筆一筆查，改成一次查詢/一次 batch 操作。本專案已有的例子：`backend/app/ingestion.py` 的 CSV 匯入走 batch insert，不是逐列 insert。
- **善用資料結構本身的複雜度優勢**：需要判斷「是否存在」或做查找時優先用 `set`/`dict`，不要對 `list` 做重複的線性掃描。
- **能用向量化操作就不要手寫迴圈**：本專案 CSV/時間序列處理已經在用 pandas，能用 pandas 的向量化運算（例如 `.apply`、boolean masking、groupby）就不要退回 Python-level 的 for-loop 逐列處理。
- **SQL 聚合優先於 Python 聚合**：能在資料庫層用 `SUM`/`COUNT`/`GROUP BY` 算完的，不要把整份資料撈進 Python 再自己算一次，浪費 I/O 也浪費運算。

**不是**要犧牲可讀性去換效率——變數命名、函式拆分還是要清楚；只是在「精簡的寫法」和「效率最高的寫法」兩者選一個的時候，選效率。

## 既有慣例（依目前 `backend/app/` 實際程式碼歸納）

- 全面使用 type hint；`Optional[X]` 而非 `X | None`（注意這跟 frontend TypeScript 端的 `str | None` 寫法相反，是兩個語言各自的慣例，不要互相套用）。
- Docstring 只在「非顯而易見」時才寫，且說明的是 WHY，不是重述程式碼在做什麼。例如 `backend/app/db.py` 的 `get_db_dependency()`：docstring 解釋的是「為什麼要包一層讓測試可以用 `dependency_overrides` 替換」，不是「這個函式回傳一個 connection」這種廢話。
- Response schema 一律用 Pydantic `BaseModel`（`backend/app/schemas.py`），欄位命名 snake_case。
- Import 順序：標準庫 → 第三方套件 → 本地模組，各段之間空一行（參考 `backend/app/db.py`：`os` 一段，`dotenv`/`sqlalchemy` 一段）。

## 適用範圍

目前這份規則主要依據 `backend/app/` 的實際程式碼歸納，`spike/` 目錄定位不同（探索性原型，見 `CLAUDE.md` 架構總覽），若之後發現 `spike/` 有明顯不同的取捨，另外討論是否需要獨立規則，不要直接套用這份文件。
