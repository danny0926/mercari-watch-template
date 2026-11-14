# Mercari 商品監控

監聽 Mercari 日本站、台灣入口、Yahoo!フリマ與駿河屋日本站的一般販售商品，透過 Discord、LINE 或兩者同時通知。搜尋使用最新排序與販賣中篩選，依來源商品編號合併結果。拍賣網站已移除，Mercari 拍賣商品預設排除。

- Discord 通知包含商品名稱、商品大圖、可點擊的商品連結與來源幣別價格。
- 同件商品跨關鍵字、跨站與跨輪次去重；每個通知目的地獨立記錄。不同賣家或不同刊登編號視為不同商品。
- 台灣站獨立讀取搜尋頁，使用「顯示可購買的商品」及「新商品」，不以日本站結果代替。
- Yahoo!フリマ只監聽固定價刊登，驗證服務端的最新排序及販售中條件；不搜尋 Yahoo!オークション。
- 駿河屋只使用 `www.suruga-ya.jp`，選「更新の新しい順」及「品切れ OFF」，確認本店售價後才通知；不同品況分開記錄，價格區間標示為起價。
- 私人搜尋條件從 `.env` 或 GitHub Secrets 載入，公開的 `watchlist.json` 保持空白範本。
- 已看紀錄加密保存，不提交商品編號、搜尋條件或執行紀錄到 Git。

## 本機設定

需要 Python 3.12 以上：

```sh
python -m venv .venv
# 啟用虛擬環境後：
python -m pip install -r requirements.txt
python -m playwright install chromium
# 駿河屋主用無頭 CloakBrowser，套件與瀏覽器都只安裝到此專案：
python setup-cloakbrowser.py
```

將 `.env.example` 複製為 `.env`。環境變數優先於檔案；程式不會覆蓋已設定的變數。

| 環境變數 | 內容 |
| --- | --- |
| `WATCHLIST_JSON` | 私人監聽條件的 JSON 陣列；`[]` 停用監聽 |
| `DISCORD_WEBHOOK_URL` | Discord incoming Webhook 網址；使用 Discord 時設定 |
| `DISCORD_WEBHOOK_URL_SECONDARY` | 可選的獨立 Discord 通道；只接收指定給它的條件 |
| `DISCORD_WEBHOOK_URL_TERTIARY` | 可選的第三個獨立 Discord 通道；只接收指定給它的條件 |
| `DISCORD_WEBHOOK_URL_QUATERNARY` | 可選的第四個獨立 Discord 通道；只接收指定給它的條件 |
| `MERCARI_LINK_MODE` | `original`（預設，標題連到商品原站）或 `buyee`（明確選擇以 Buyee 代購頁作主連結） |
| `SURUGAYA_BROWSER_BACKEND` | `cloakbrowser`（預設，無頭主用）或 `patchright`（手動選用的有頭備援） |
| `CLOAKBROWSER_CACHE_DIR` | 預設 `.state/cloakbrowser`，必須位於專案內；保存官方瀏覽器本體 |
| `CLOAKBROWSER_VERSION` | 固定的免登入瀏覽器版本，預設 `146.0.7680.177.5`；自動更新停用 |
| `SURUGAYA_BROWSER_PROFILE` | 選用；預設 `.state/browser-profiles/surugaya-cloakbrowser`，必須位於專案內 |
| `SURUGAYA_BROWSER_CHANNEL` | 手動選擇 Patchright 時的 channel；Windows 預設 `msedge`、Linux 預設 `chrome` |
| `LINE_CHANNEL_ACCESS_TOKEN` / `LINE_USER_ID` | 使用 LINE 時須同時設定 |
| `MONITOR_STATE_KEY` | Fernet 加密金鑰；正式保存紀錄必填 |
| `MONITOR_STATE_PATH` | 加密紀錄位置，預設 `.state/seen.enc` |
| `MONITOR_GITHUB_REPOSITORY` | 本機交接用的 `owner/repo`，明確填自己的 fork；不從 Git remotes 推測 |
| `LOCAL_MONITOR_INTERVAL_SECONDS` | 本機每輪完成後的等待秒數，預設 `1800`，最少 `60` |

產生加密金鑰，放入自己的 `.env` 與同名 GitHub Secret，後續執行使用相同金鑰：

```sh
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

`WATCHLIST_JSON` 的通用格式如下；實際搜尋詞僅填在自己的 `.env`。JSON 可放在單引號內，正規表示式的反斜線需符合 JSON 與 dotenv 的跳脫規則。

```dotenv
WATCHLIST_JSON='[{"id":"watch-1","name":"商品A","keyword":"範例商品","keywords":[],"sources":["jp","tw"],"source_keywords":{},"price_min":null,"price_max":null,"must_match":[],"must_not_match":[],"include_auctions":false,"review_note":"","enabled":true}]'
```

| 商品欄位 | 說明 |
| --- | --- |
| `id` | 不同條件使用不同且固定的代號 |
| `name` | 通知顯示名稱 |
| `keyword` | 主要搜尋詞，必填 |
| `keywords` | 搜尋詞陣列，逐一搜尋後合併；空陣列使用 `keyword` |
| `sources` | 可選 `jp`、`tw`、`yahoo_fleamarket`、`surugaya`；省略時維持 Mercari 日本站；不接受拍賣網站 |
| `source_keywords` | 為啟用的來源分別指定搜尋詞陣列，避免每個網站都搜尋全部同義詞 |
| `discord_webhook_env` | Discord 目的地環境變數名稱；省略使用 `DISCORD_WEBHOOK_URL` |
| `price_min` / `price_max` | 日圓價格篩選；使用 `tw` 的條件請留 `null`，避免將台幣與日圓混用 |
| `must_match` / `must_not_match` | 標題須符合／不得符合的正規表示式陣列 |
| `include_auctions` | 日本站是否接受拍賣商品，省略與範本均為 `false`；一般販售監聽請保持關閉 |
| `notify_restock` | 選用、預設 `false`；駿河屋同一商品／品況在兩輪完整成功搜尋中未出現，之後重新出現時另發「重新販售」通知 |
| `review_note` | 人工核對提示 |
| `enabled` | 是否啟用 |

首次成功搜尋每一組條件與來源時，只建立基準。之後出現的新商品才通知；單一來源失敗時保留該來源紀錄，其他來源仍會處理。未啟用條件時不搜尋、不推播、不寫入紀錄。

駿河屋的商品編號代表商品／品況，不能視為每次入荷的獨立刊登編號。私人條件可設定 `notify_restock=true`，在保留既有去重紀錄的同時追蹤重新販售。首次啟用只記錄當下在售狀態；穩定在售、單純價格改變不會重發。搜尋失敗、結果分頁未全部涵蓋，或有預約品無法確認在售品況時，不推定缺貨；通知失敗會留待下輪重試。變更搜尋條件會重新建立觀察基準。觀察狀態與原歷史一起加密保存並交接。

「重新販售」表示程式觀察到販售結果消失後再出現，不能證明商店的實際入荷時間。若兩次輪詢之間已完成售出及補貨，或持續有庫存時增加同款庫存，現有搜尋資料無法可靠識別；也不把排序前移或一直顯示的「新入荷・再入荷」字樣直接當作新事件。

若標題只寫品牌、比例或套組名稱，可新增獨立規則擴大搜尋入口，並使用 `must_match_anywhere`／`must_not_match_anywhere` 正規表示式比對同筆刊登的標題與商品說明；原有 `must_match`／`must_not_match` 仍只檢查標題。說明讀取目前支援有可核對日本編號的 Mercari 一般商品與 Shops，同一輪共用讀取快取。這是文字規則比對，不能自動判斷只有圖片能辨識的角色；說明缺少或不符合條件時，預設不通知，只有 `review_unconfirmed=true` 才以「【候補】角色尚未確認」通知。明確符合排除規則的項目仍會略過。

只接受已確認文字條件的通知時，維持 `review_unconfirmed=false`。候補提醒須明確啟用，不應將套組名稱本身當作角色符合的依據。

擴大條件時可使用新的規則 `id`，讓其他舊刊登先建立基準。若需補查特定刊登，將其編號放在該規則的 `catchup_ids`（最多 50 個，實際資料只放 `.env`／Secrets）；命中搜尋與篩選後以「【補查】」通知。補查與成功通知憑證會寫入加密歷史；送出失敗會保留重試資格，已完成補查的編號不重播。近期成功通知保留時間、原因與判斷依據，既有舊歷史仍無法反推是否曾通知。

不同規則可以指定不同 Discord 通道。例如第二組在私人 JSON 中加上 `"discord_webhook_env":"DISCORD_WEBHOOK_URL_SECONDARY"`，並在 `.env`／GitHub Secret 填入同名 Webhook。只接受 `DISCORD_WEBHOOK_URL` 或 `DISCORD_WEBHOOK_URL_` 後接大寫英數與底線的名稱；增加其他名稱時，也須同步加入 workflow 的環境變數。

自訂 Discord 目的地不會轉送到預設 Discord 或 LINE。目的地未設定時回報失敗，不會改送其他頻道。原有單通道去重紀錄會延續到預設通道，新通道首次建立自己的基準；同件商品若符合不同通道條件，可在各通道各收到一次。

第三、第四個目的地分別使用 `DISCORD_WEBHOOK_URL_TERTIARY`、`DISCORD_WEBHOOK_URL_QUATERNARY`，並在私人條件的 `discord_webhook_env` 指定同名變數；雲端來源工作、連線測試與計時異常警告均會讀取這些可選目的地。實際分流條件與通道憑證僅放在 `.env`／Secrets。

```sh
python mercari_watch.py --once --dry-run
python mercari_watch.py --test-discord
python mercari_watch.py --test-line
python mercari_watch.py --once
# 只執行某來源，私人條件仍從 .env 載入：
python mercari_watch.py --once --source surugaya
python -m unittest -q
```

測試通知以「【測試】」開頭，只發送純文字，不搜尋商品或修改去重紀錄；`--test-discord` 會測試所有已設定的 Discord 通道。試跑不發通知、不保存紀錄。

## Discord 設定

1. 在 Discord 建立文字頻道。
2. 伺服器設定 → 整合 → Webhook → 新增 Webhook，選擇頻道並複製網址。
3. 將網址填入 `.env` 的 `DISCORD_WEBHOOK_URL`，或 GitHub 同名 Secret。
4. 將接收頻道通知設為「所有訊息」，開啟 Discord 與手機系統的通知權限。

商品圖片由商品來源提供；缺少圖片時仍保留名稱與連結。兩站皆找到相同商品時合併連結。台灣站以新台幣顯示，日本站以日圓顯示，不自行推算匯率。圖片與商品內容需自行核對。

`MERCARI_LINK_MODE=original` 保留商品原站作為 Discord 標題及 LINE 查看按鈕的主連結。經商品編號核對的 Mercari 日本站通知使用明確的日文路徑 `/ja/item/…`、`/ja/shops/product/…`，台灣站連結保留。Discord 另外標示商品來源，店家刊登標為「Mercari Shops 日本站」；可核對商品編號時，另附「Buyee 代購入口（非原站）」。Buyee 是代購服務，並非商品來源，也不代表監聽新增了 Buyee 網站。

日文商品連結沿用 Mercari 原站登入流程。若原站宣傳彈窗覆蓋頁面，先關閉，再回到頁面頂端點「ログイン」；登入由 Mercari 網站處理。

已重現的轉區原因是瀏覽器的 `gopWebRedirection=tw` cookie：沒有語系前綴的日本商品網址會回傳 HTTP 307，導至台灣的轉址入口，再到台灣商品頁。明確的 `/ja/` 商品路徑可避開本次確認的轉址規則；通知只調整開啟路徑，原商品編號、搜尋來源與去重紀錄不變，不讀寫使用者瀏覽器的 cookie。網站未來改版或 App 接管開啟時仍需另行確認。

只有明確希望以 Buyee 作主入口時，才在 `.env` 與 GitHub 同名 Secret 設定 `MERCARI_LINK_MODE=buyee`；這會更換開啟的網站。該模式在 Discord 將日本原站日文連結放在可複製欄位，保留來源標示。一般商品及具有匹配日本原始網址的 22 字元 Mercari Shops 商品編號可轉換；無法核對時不猜測。其他網站維持原連結。

`tw.mercari.com` 是跨境商品入口，並非台灣本地現貨市場；其台幣標價不能視為已包含全部跨境費用的到手價。不同賣家刊登同款商品仍分別通知，不以名稱相似判定同一件貨品。

Yahoo 新增來源同樣首次只建立基準，不重播既有商品。搜尋被拒絕、驗證頁、無法確認排序／庫存或資料不完整都會回報失敗。Yahoo 部分有效搜尋會回傳 HTTP 404，僅在服務端搜尋資料與篩選皆驗證成功時接受；缺少搜尋資料的 404 仍失敗。程式不把來源失敗解讀為零商品，也不使用代理或解驗證服務。

台灣來源以原生的「沒有相符的商品」元件確認零結果，仍須驗證「可購買」與「新商品」篩選；空白頁、載入失敗與錯誤頁不視為零結果。Check workflow 的 `taiwan_probe` 可驗證公開的有商品／零結果案例；`taiwan_probe_private` 會以 Secrets 中的實際搜尋條件驗證，只記錄查詢序號、筆數與載入階段，不送通知、不更改去重紀錄、不輸出搜尋詞。

Check workflow 的 `state_audit` 可唯讀檢查指定刊登是否已進入加密歷史，以及是否有近期成功通知憑證。參考資料只放 `.env`／同名 Secret 的 `MONITOR_AUDIT_JSON`，格式為含 `route`、`watch_id`、`identities` 的物件陣列；公開範本保持空陣列。稽核只輸出序號、布林值及固定的判斷依據／通知原因代碼，不搜尋、不通知、不儲存狀態。「已知」可能代表首次基準或曾通知；沒有憑證的舊紀錄無法再區分。

## 台灣比價評估

目前保留監聽、文字條件篩選與相同刊登 ID 去重；另有下述選用的本機收藏圖片候選比對。尚未實作跨市場商品配對、台灣價格擷取或到手價計算。收藏比對使用本機模型，不呼叫付費模型 API；這不等於已驗證商品配對或比價品質。比價仍需核對系列、版別、品況、數量與配件，資料不足時保留未知；原有比價方案見 [比價評估](PRICE_COMPARISON.md)。

## 駿河屋日本站

`surugaya` 主用 [CloakBrowser](https://github.com/CloakHQ/CloakBrowser) 無頭模式及獨立 profile，不開啟可見網頁視窗。`setup-cloakbrowser.py` 將 Python 套件裝進專案 `.venv`，官方瀏覽器下載到 `.state/cloakbrowser/`，暫存檔使用 `.state/browser-tmp/`；不進行全域安裝，設定到專案外的路徑會被拒絕。瀏覽器子程序不繼承包含私人規則、通知憑證或加密金鑰的環境變數；搜尋詞仍會用在網站請求中。

目前固定 Python wrapper `0.6.4` 與免登入 Chromium `146.0.7680.177.5`，停用自動更新；不取得額外授權、不使用付費代理。wrapper 為 MIT，瀏覽器本體適用不同的 [Binary License](https://github.com/CloakHQ/CloakBrowser/blob/main/BINARY-LICENSE.md)，不隨本 repo 散布或上傳公開 Cache／Artifacts。目前專案整合不啟用帶 license key 的版本，因其額外儲存路徑與條件需要另行處理。需要維護性切換時，可明確設定 `SURUGAYA_BROWSER_BACKEND=patchright` 使用原本有頭方案；程式不會在無頭失敗時自動開視窗。

網站要求人工驗證時，程式回報 `verification` 並停止當輪後續駿河屋查詢，不點擊或操作驗證控制；需由維護者另行處理。沒有驗證 frame 但結果逾時則回報 `browser-timeout`，兩者都不當成零商品。

Check workflow 的 `surugaya_probe` 在獨立 Windows job 驗證通用 DOM 範例、原生搜尋與公開商品圖片，不讀私人條件或通知憑證。首頁能開啟不代表排序、庫存、價格與圖片皆可用；網站仍可能變更驗證要求。

本機 CloakBrowser 無頭讀取已驗證可用；GitHub Windows runner 的相同無頭方案在本次驗證仍停留於 Cloudflare 驗證頁，因此雲端備援明確使用既有 Patchright／Edge，視窗只出現在遠端 runner。本機不會自動切換成有頭。`surugaya_probe` 的 `surugaya_browser` 可分別檢查兩種環境，避免把本機成功當成雲端也成功。

監聽「更新的商品」，不等同首次上市；只處理本次載入的搜尋頁。網站的「品切れ OFF」仍可能包含本店缺貨但其他賣家有貨的商品，因此程式另外確認本店新品／中古售價，略過第三方獨有商品與預約品。不將定價、運費門檻、手續費或第三方最低價當作本店售價。區間價標示「起」，不同分支品況與新品／中古使用不同 ID；它們仍需人工核對內容。限時特價從本店專用欄位讀取，即使同卡先列另一種品況的一般售價，仍分別配對各自的原價標籤、特價與活動期間。驗證日本時間並標明截止時間，不使用劃掉的原價；特價不改變去重 ID，也不因價格變動重新通知。未知或過期的特價版型仍回報來源失敗，保留既有紀錄。駿河屋錯誤紀錄包含固定原因代碼，不輸出私人搜尋詞或瀏覽器網址。

圖片入口可能受驗證保護；只在商品需要通知時，沿網站實際圖片重新導向取得公開 CDN 網址，不猜圖片路徑。無法確認圖片時保留名稱與連結。瀏覽器 profile 包含瀏覽紀錄與網站 cookie，僅存專案內，不提交或上傳 Actions Cache。雲端只保存原有加密去重檔；每次新 runner 都必須下載官方瀏覽器並重新通過網站檢查。來源失敗不會變成零商品，也不建立假的基準；不保證永遠能通過驗證。不需模型 API、付費代理或解驗證服務。

工作流程將 Mercari 日本站、台灣入口與 Yahoo!フリマ留在 Linux，駿河屋由獨立 Windows job 執行 `--source surugaya`。兩邊分別快取 `.state/seen.enc` 與 `.state/surugaya-seen.enc`，共用私人規則與加密金鑰，各自首次建立基準；既有 Mercari／Yahoo 去重紀錄不需重置，停用來源的歷史也保留。只執行指定來源時，程式不搜尋其他來源，也保留同一狀態檔中其他來源的紀錄與健康狀態。

## GitHub 雲端排程

1. 使用自己的 repository。公開 fork 中只保留程式與範本。
2. 在 Settings → Secrets and variables → Actions → Secrets 設定 `WATCHLIST_JSON`、`MONITOR_STATE_KEY`，以及通知通道憑證。至少設定一種通知通道。
3. 在 Settings → Environments 建立 `monitor-clock-30m`，設定 Wait timer 為 **30 分鐘**；再建立 `monitor-clock-bootstrap`，Wait timer 為 **1 分鐘**。兩者均不設定 required reviewers。這些名稱只表示計時間隔，不包含私人條件。
4. 在 Variables 設定 `MONITOR_ENABLED=true`，到 Actions → **Monitor clock** → Run workflow；正常啟動保持 `bootstrap=false`。雲端計時器每輪自動啟動監聽，再接續下一輪，間隔約 30 分鐘，仍可能受 GitHub 排隊時間影響。首次驗收可用 `bootstrap=true`，先以一分鐘計時自動交接；下一輪固定使用正式 30 分鐘計時。
5. 看 [雲端計時紀錄](https://github.com/danny0926/mercari-watch-template/actions/workflows/monitor-clock.yml) 的等待狀態與下一輪，以及 [監聽執行紀錄](https://github.com/danny0926/mercari-watch-template/actions/workflows/market-monitor.yml)。自動監聽標題為 `Automatic monitor from clock …`，對應父計時 run。`workflow_dispatch` 可由使用者或雲端程式呼叫；事件名稱本身不能區分手動與自動，應連同父計時紀錄、觸發者及時間查看。
6. 單次檢查或通知測試仍使用 **Mercari monitor** → Run workflow；勾選 `test_discord` 或 `test_line` 可測試通知。`source` 可限制單一來源，搜尋詞仍只從 Secrets 讀取。來源失敗會保留其紀錄，其他來源繼續處理。

原生 cron 在本次實際觀察期間沒有產生 `schedule` 事件，因此正式流程已改用 GitHub environment wait timer，不將「設定了 cron」當作排程成功。此方案使用公開 repo 可用的等待計時功能；等待由 GitHub 處理，無須本機保持開機，也不呼叫模型。等待期間不計入執行計費時間，見 [GitHub 官方說明](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments)。計時流程只使用目前 repo 的 `GITHUB_TOKEN`，不需要額外 PAT。請先設定 environment；程式會核對等候時間，缺少或不符時停止並告警，避免連續快速啟動。

停止時將 `MONITOR_ENABLED=false`；若要立即終止等待，也可取消 **Monitor clock** 正在等待的 run。已開始的來源工作可自行完成。重啟時設回 `true`，再執行一次 **Monitor clock**。工作被取消、workflow 被停用或持續 API 故障可能中斷接力；計時設定或交接失敗會向已設定的 Discord 通道發送警告，但故意取消不當作故障。來源健康警報只在程式啟動後運作，仍應核對最近的計時與監聽時間。

去重紀錄以 Fernet 加密檔存入 Actions Cache，金鑰保存在 Secrets；工作流程不再提交 `seen.json`。本機交接另使用短期加密 Artifact 與加密的 Secrets 傳輸，見下節。快取可能遭清除，缺少紀錄時會重新建立基準，不將現有商品整批推送；本機交接若找不到任一來源的雲端紀錄則停止，避免用不明紀錄接手。請保留加密金鑰，變更金鑰前需先清除舊加密紀錄。

各目的地獨立保存發送結果，失敗只重試該目的地，成功目的地不受影響。預設目的地若同時設定 LINE 與 Discord，仍須兩者都成功才推進該目的地紀錄；其中一邊成功、分批中途失敗或送達後連線中斷時，該目的地先前成功的訊息可能重複。來源異常與恢復訊息也會送往對應目的地。Discord 限流依服務回傳時間做有限次重試。

Discord Webhook 基本功能不需 Nitro。公開專案使用標準 GitHub-hosted runner 免費；私人專案受帳號免費額度與超額計費規則限制。[Discord 說明](https://discord.com/safety/using-webhooks-and-embeds)、[GitHub 計費](https://docs.github.com/en/billing/concepts/product-billing/github-actions)。

## 本機監聽與雲端交接

`local_monitor.py` 使用相同的私人條件、通知分流與篩選。啟動時暫停雲端自動監聽，正常停止時交回去重紀錄並恢復原先開關；不需要心跳服務、self-hosted runner 或額外雲端帳號。若雲端原先就停用，停止本機後也維持停用。

先將程式與 `monitor-handoff.yml` 部署到自己 repo 的 `main`，完成上節雲端設定，安裝 [GitHub CLI](https://cli.github.com/)，執行 `gh auth login`。本機帳號須能讀取 Actions／Artifacts、啟動與取消 workflows、寫入 repo Variables 與 Secrets。沿用已登入的帳號即可，不將 GitHub token 寫入公開檔案。`.env` 另填 `MONITOR_GITHUB_REPOSITORY=owner/repo`，搜尋條件、通知憑證與 `MONITOR_STATE_KEY` 須與雲端一致。

Windows 本機常駐需要已安裝的 Node.js、PM2 與專案 `.venv`；控制程式會沿 Node 模組搜尋路徑、PATH 與 `%APPDATA%\npm` 找到現有 PM2，不會自動安裝。可雙擊 `start-local.cmd`，或在專案目錄執行：

```powershell
# 啟動背景服務後立即返回；重複啟動不重啟健康的程序
.\start-local.cmd
# PM2 程序狀態（不輸出私人環境變數）
node .\pm2-local.cjs status
# 監聽權、實際間隔與最近一輪結果
.\start-local.cmd --status
# 查看本服務的輸出；Ctrl+C 只離開日誌查看
pm2 logs mercari-watch --lines 50
# 完成當輪與交接後停止；start-local.cmd --stop 也走相同流程
.\stop-local.cmd
# 完成交接後才重新啟動、接回本機監聽權
node .\pm2-local.cjs restart
```

服務名稱固定為 `mercari-watch`，單一 Node supervisor 以 PM2 fork 模式啟動單一 Python worker；原有監聽迴圈、程序鎖與加密交接仍由 `local_monitor.py` 負責。同名服務若指向不同程式或工作目錄，控制程式會拒絕操作；所有控制只影響本服務，不會停止、重啟、刪除或儲存其他 PM2 應用。私人設定只放專案 `.env`，不放進 ecosystem 或 PM2 env 宣告；受管啟動以目前 `.env` 的值覆蓋 daemon 可能保留的同名舊設定。既有公仔暫停、補貨規則、監聽間隔與 Discord 分流名稱保持原樣。

Windows 瀏覽器啟動會先確認專案 Playwright 套件內的 Node 能執行；若它損壞或崩潰，沿用專案已安裝的 Patchright Node，僅設定目前 Python 程序的 `PLAYWRIGHT_NODEJS_PATH`，不修改套件或 PM2 daemon。明確設定的 `PLAYWRIGHT_NODEJS_PATH` 保持原值。台灣來源優先使用匹配版本的 Playwright Chromium；其快取缺少時使用已安裝的 Edge 無頭模式及新建的暫存 profile，不下載瀏覽器、不使用使用者或駿河屋的 profile。兩個 runtime 都不可用、或沒有可用的 Edge 時仍回報失敗，需修復專案依賴或既有瀏覽器安裝。

程式先設 `LOCAL_MONITOR_ACTIVE=true`、`MONITOR_ENABLED=false`，取消雲端計時器並等待正在執行的商品監聽完成。它不會中途取消來源工作；正常交接仍需等候 GitHub 排隊與 runner 啟動。`Monitor state handoff` 將兩個來源分組的紀錄加密後輸出為一天有效的 Artifacts，本機驗證金鑰與交接代號後才開始搜尋。若任一分組缺少或無法解密，不啟動本機監聽。CI 測試不受開關影響；持有本機監聽權時，手動啟動的雲端商品監聽也會略過。

**停止或重啟請使用上述控制命令，等候「交接完成」。** PM2 透過 Windows shutdown IPC 通知 supervisor；它持續保留既有 `stop.request`，涵蓋 Python 啟動時清除舊標記的競爭情況，並等待 Python 自行退出，不自行終止子程序。程式會完成當輪，將兩份紀錄壓縮後再以既有金鑰加密，經專用 Secrets 傳給 import workflow。兩個分組都成功存入原本的 Cache 後，才解除本機監聽權並恢復雲端計時。暫存 Secrets 隨後刪除；公開輸入僅包含隨機交接代號，不包含商品編號、搜尋條件或憑證。此流程有傳輸大小上限，超限時保留紀錄並停止交接。PM2 等待上限為 30 分鐘，供當輪搜尋及原有最長 900 秒的 transfer 等待使用；若超時遭 PM2 強制結束，需先確認程序已退出，再走下述人工復原。

也可執行 `python local_monitor.py --stop`，透過原有標記要求完成當輪後交還雲端。受管程序即使最後一輪有來源錯誤，主動停止完成交接後仍以正常停止結束，不會自動重啟。`--status` 會顯示最近一輪完成時間與來源錯誤數，方便確認本機是否已實際執行搜尋；PM2 顯示 online 僅代表 supervisor 正在執行，仍須透過日誌與本機狀態確認交接及搜尋已就緒。

等待時間從 `.env` 的 `LOCAL_MONITOR_INTERVAL_SECONDS` 讀取，`--status` 顯示程序實際採用的秒數。這是每輪完成後的等待時間；搜尋耗時另外計算，且不會重疊執行。變更設定需使用上述 restart 命令，先完整交回雲端再重新接手。PM2 因意外子程序失敗重試時，`--managed-local` 只在既有紀錄為 `local` 時呼叫原有 `continue_local()`，核對雲端仍暫停、程序鎖與兩份加密歷史；沒有紀錄或已完成 `cloud` 則走正常啟動。交接中的其他階段、驗證失敗或交回失敗以復原代碼 78 停止，不自動重啟；請確認舊程序已退出後執行 `--resume-cloud`，再重新 start。控制程式的 restart 會比對該次 supervisor 的完成紀錄，無法確認正常交接時停止，不直接啟動新一代；不單憑 PM2 可能尚未更新的退出代碼判斷成功。

意外子程序失敗交由 PM2 做有限啟動重試：延遲由 3 秒逐步增加、最高 15 秒，`min_uptime=10m`、`max_restarts=5` 限制啟動期的不穩定失敗；長時間穩定執行後的失敗不算同一啟動失敗批次。正常停止 0 與需復原 78 均列在 `stop_exit_codes`，不自動重啟。日誌位於忽略的 `.state/pm2/out.log` 與 `error.log`；日誌沒有配置自動輪替，需留意磁碟空間。

本機可將 `start-pm2-hidden.vbs` 的捷徑放入目前 Windows 使用者的「啟動」資料夾：登入後隱藏呼叫既有 `pm2-local.cjs start`，沿用單一程序與交接檢查，不保存其他 PM2 程序或私人環境變數。捷徑必須指向此專案中的腳本，移動專案後需更新。啟動結果記在 `.state/pm2/startup.log`；成功只代表啟動命令完成，仍需以 `status` 和日誌確認實際搜尋。此方式需要使用者登入，並不保證關機或尚未登入時由雲端接手。`pm2 save` 本身不會設定 Windows 開機啟動。

```powershell
# 原有前景模式仍可使用；停止時按一次 Ctrl+C，等交接完成
.\.venv\Scripts\python.exe -X utf8 -u local_monitor.py
# 查看狀態，不切換監聽
.\.venv\Scripts\python.exe local_monitor.py --status
# 完整交接一次，但不搜尋、不發商品通知
.\.venv\Scripts\python.exe -u local_monitor.py --handoff-only
# 執行一輪正式本機監聽後交回雲端
.\.venv\Scripts\python.exe -u local_monitor.py --once
# 強制結束、斷電或交接失敗後，在原電腦重試交回紀錄
.\.venv\Scripts\python.exe -u local_monitor.py --resume-cloud
```

原有 `--once`、`--handoff-only`、`--resume-cloud`、`--status`、`--continue-local` 等參數可經 `start-local.cmd` 直接交給 Python；它們不啟動 PM2。`--continue-local` 保留給確認舊程序已退出後的手動維護；PM2 正常 restart 則完整交回再接手。各模式互斥，復原前不可讓其他本機程序同時持有監聽權。

本機紀錄與交接進度保存在忽略的 `.state/local-monitor/`。不要清除它們來解除暫停；應先執行 `--resume-cloud`。突然斷電、強制結束或前景模式直接關閉視窗可能無法交還雲端；PM2 只重試可驗證的本機延續，不會讓雲端自動接管不明階段。發送通知與保存紀錄之間若意外中斷，仍可能重送少量訊息。駿河屋主用無頭瀏覽器；只有手動選擇 Patchright 備援時才需要可用的互動桌面。

## 私人本機收藏圖片比對（選用）

每張 Discord 商品卡會增加「本機收藏圖片比對」欄位。預設 `COLLECTION_COMPARE_ENABLED=false` 顯示「未啟用」，不額外下載圖片或載入模型。啟用後，比對既有通知商品的賣場圖片與自己手動登錄的收藏照片；最多列出 **3 件不同收藏的視覺候選**。同件收藏的多張照片不占用多個名額。原來的賣場大圖、商品名稱、價格、連結與通知分流繼續保留；不建立空白候選圖、不增加堆疊的大型卡片，也不因收藏比對刪除任何既有通知。

候選以 `1、2、3` 對應同張卡片右側的一張編號拼圖縮圖，使用真實收藏照片等比例縮放與留白，可在 Discord 點開查看。附件用官方 `payload_json` / `files[n]` multipart 格式發送，名稱僅為 `collection-1.jpg` 等通用名稱；多件商品分批時，每張卡片只引用自己的附件。Discord 各裝置的縮圖大小、裁切與點開行為仍由客戶端決定；本專案以離線請求驗證附件與卡片對應，沒有替使用者發送實際訊息驗證各裝置畫面。編號拼圖小圖可能不易直接辨認，請點開後核對。

安裝一次（Python 3.12 以上，在本專案目錄）：

```powershell
python -B setup-collection.py
$catalogPython = '.state/collection-runtime/venv/Scripts/python.exe'
& $catalogPython -B collection_catalog.py init
```

Linux 的專用 Python 位於 `.state/collection-runtime/venv/bin/python`，其他參數相同。安裝器直接下載並核對 [Orchard Photos v0.5.0](https://github.com/chaseleantj/orchard-photos/releases/tag/v0.5.0) 的固定 commit 與來源 ZIP SHA-256；直接呼叫其原有 Scanner、Encoder 和 SemanticIndex。模型為 Google SigLIP 2 的固定 ONNX 匯出，第一次需下載約 **690 MB**；需要另外預留虛擬環境、pip 快取與索引空間。CPU 版不需要付費 API、API key 或雲端 AI，也不更改監聽用的 `.venv` / requirements。安裝失敗會停止並回報，修正網路或安裝環境後可再次執行同一指令。

以檔案總管把自己擁有的 JPEG、PNG 或 WebP **靜態照片**手動複製到 `.state/collection/inbox/`。每張最多 6 MB、2 千萬像素；整個目錄最多 500 件收藏、1000 張照片。所有輸入路徑必須位於本專案 `.state` 內，不接受外部路徑或連到外部的 symlink/junction。以下都是非真實範例：

```powershell
# 第一張照片；id 自行指定且固定，name 是將顯示在 Discord 的收藏名稱。
& $catalogPython -B collection_catalog.py add --id example-001 --name '範例收藏A' --photo '.state/collection/inbox/front.jpg'
# 同一收藏追加另一角度；也可以在同一指令重複 --photo。
& $catalogPython -B collection_catalog.py add --id example-001 --photo '.state/collection/inbox/back.png'
# 改顯示名稱，不改私人 ID，也不需要重加照片。
& $catalogPython -B collection_catalog.py add --id example-001 --name '範例收藏A（新版名稱）'
# 移除第 1 張照片（依加入順序，移除後重新編號），或移除整件收藏。
& $catalogPython -B collection_catalog.py remove --id example-001 --photo-number 1
& $catalogPython -B collection_catalog.py remove --id example-001
& $catalogPython -B collection_catalog.py status
```

也能先只用 `add --id example-002 --name '範例收藏B'` 建立零張照片的項目；加入第一張照片後才可參與比對。`add` 將照片**原始位元組完整複製**至私人 `originals/`，不重壓或剝除原檔 EXIF；匯入後可自行移除 inbox 的副本，日後請用上述指令增刪正式收藏。`remove` 會刪除選定正式原檔並更新目錄，請先自行備份要保留的照片。狀態指令只列數量，不在日誌列私人名稱或檔案路徑。

最後在自己的 `.env` 設定：

```dotenv
COLLECTION_COMPARE_ENABLED=true
COLLECTION_CATALOG_DIR=.state/collection
```

此設定不會新增、啟用或修改任何監聽規則與通知目的地；原本停用的模型／公仔規則仍停用。修改照片或收藏名稱後，下一次既有商品通知比對會重新掃描並更新索引，**不用手動重建索引或重啟監聽**。改環境設定本身仍須由原有服務載入新設定，部署由操作者處理。

資料位置均被 `.gitignore` 的 `.state/` 排除：

| 路徑 | 內容 |
| --- | --- |
| `.state/collection/catalog.json`、`originals/` | 私人 ID、顯示名稱及保留原始位元組的收藏照片 |
| `.state/collection/inbox/` | 自己手動複製的待匯入照片；不會被自動當作收藏 |
| `.state/collection/comparison.jpg` | 手動執行 compare 時產生的候選照片拼圖 |
| `.state/collection-runtime/orchard/` | 原版 Orchard 固定來源與原 LICENSE |
| `.state/collection-runtime/venv/`、`models/`、`indexes/` | 隔離套件、固定模型、每個收藏目錄獨立的索引和縮圖 |
| `.state/collection-runtime/licenses/` | 原始／ONNX 模型卡與 Apache-2.0 授權全文 |
| `.state/collection-runtime/tmp/`、`pip-cache/`、`home/`、`cache/` | 專用暫存、套件下載、HF/Xet 與其他套件的本機資料 |

程序使用明確的專案內路徑，啟動子程序前重新設定 HOME、TEMP、HF/pip/XDG 快取，移除 Webhook、搜尋條件、登入 token 與外部套件路徑；掃描僅限已登錄的照片，不開啟 Orchard 桌面介面、HTTP API 或公開服務。原版 HTTP API 已檢查，其 `/api/search/image` 為本機圖片搜尋；本整合直接使用同一搜尋實作，省去開放本機服務的需要。每批最多 10 張賣場圖，子程序最多等待 120 秒，下載僅允許已知商品圖片 CDN 的 HTTPS 公開位址，不跟隨重新導向、不使用環境代理，限制下載時間、大小、格式與解碼像素；超出限制只回報無法比對。原始賣場圖片仍由既有卡片顯示。

**收藏照片與候選名稱會依使用者的選擇，作為附件／欄位送到該商品原有的 Discord 通道。** 這是明確的對外分享，請確認通道成員可以看到它們。傳送的是去除 EXIF 的有界候選拼圖；不傳原檔路徑、原檔名或私人 ID，不建立公開圖片網址；本機原檔保持不變。不要把收藏、索引、日誌、模型目錄加入 Git、Artifacts 或 Actions Cache。既有加密去重／雲端交接不包含本機收藏。

GitHub hosted runner 沒有你的本機收藏或模型，也不會自動下載它們；維持功能停用，或如實顯示未就緒。這個本機功能不會把收藏上傳雲端以補足缺失。沒有收藏照片顯示「未比對：本機收藏沒有照片」；賣場缺圖、圖片下載失敗、模型／套件缺失、收藏損壞或超時各顯示未比對／無法比對。部分收藏照片遺失或無法解碼時，若仍可找出候選會標示照片不完整；全部無法讀取則無法比對，不回報未收藏。

排序使用 Orchard 的真實 SigLIP 2 cosine 相似度；保留上游圖片搜尋 `0.70` 的候選展示門檻，但**尚未以你的收藏校準**。分數不是機率，也不表示商品相同或已擁有。即使無候選，也只表示沒有可展示候選，不能斷言未收藏。相似背景、角色配色、包裝與不同版別可能互相誤排；同款不同角度也可能漏掉。程式不自動過濾任何通知。

可先離線驗證自己的照片，不發 Discord 訊息、不讀監聽歷史：把同件收藏的另一個角度與一張不同物品照片放入 inbox，依序執行並在本機開啟 `comparison.jpg` 核對編號與私人 `catalog.json` 的名稱。終端只列候選序號和 cosine，避免把私人名稱寫入日誌；同款照片是否找對、不同照片是否誤排，都需要人工核對，不能以一次成功推估準確率。

```powershell
& $catalogPython -B collection_catalog.py compare --photo '.state/collection/inbox/another-angle.jpg'
& $catalogPython -B collection_catalog.py compare --photo '.state/collection/inbox/different-object.png'
# 最小離線檢查；不下載模型、不讀私人收藏、不送通知。
.venv/Scripts/python.exe -B -m unittest -q test_monitor test_collection
& $catalogPython -B -m unittest -q test_collection_catalog
```

來源與授權：[Orchard Photos（MIT）](https://github.com/chaseleantj/orchard-photos)、[Google SigLIP 2（Apache-2.0）](https://huggingface.co/google/siglip2-base-patch16-256)、[固定 ONNX 匯出](https://huggingface.co/onnx-community/siglip2-base-patch16-256-ONNX/tree/d1114256522a37ffa257a0a58017348ab0058db2)。ONNX 匯出模型卡指向 Google 原模型，未另列不同授權；沒有重新授權模型。完整來源與 MIT notice 見 [NOTICE](NOTICE)。已選 Orchard，因其可直接沿用原有掃描、持久化索引、固定模型與搜尋 API；沒有另建嵌入／排名模型，也未聲稱優於其他模型。備選 [rclip（MIT）](https://github.com/yurijmikhalevich/rclip) 此次未安裝，無須再引入第二套檢索與快取流程。

## 資料與限制

搜尋只處理本次回傳／頁面已載入的商品，不保證即時或完整涵蓋。標題篩選不辨識圖片，也不保證商品真偽、內容、庫存或跨境購買資格。程式不登入商品平台，不使用付費代理或第三方解驗證服務。

本機 `.env`、`.state/`、執行紀錄與真實商品資料不得提交。公開範例、測試、README、版本說明與標籤均不包含個人搜尋內容。不要將私人條件放入 GitHub Variables、issue、commit 或 workflow 輸入。

## 版本與授權

版本標籤採 `vMAJOR.MINOR.PATCH`；版本變更見 [CHANGELOG.md](CHANGELOG.md)。

本專案 fork 自 [1212k10969/mercari-watch-template](https://github.com/1212k10969/mercari-watch-template)，基準為 `5a19a755a758b36f5bce2d3e1dc3e20f146c7e44`。上游基準未附授權；本 fork 的 MIT 許可僅涵蓋本次新增檔案與修改部分，不代表可重新授權上游原始程式。授權範圍與來源詳見 [LICENSE](LICENSE) 和 [NOTICE](NOTICE)。

