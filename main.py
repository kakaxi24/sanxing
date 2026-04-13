import flet as ft
from datetime import datetime, timedelta
import time
import threading
import requests
import re
import urllib3
import subprocess
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

# 屏蔽 SSL 警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==========================================
# --- 核心逻辑引擎 ---
# ==========================================
class LotteryEngine:
    def __init__(self):
        # 哈希三分彩 API
        self.api_url = "https://qqtj666.com/api/trial/draw-result?code=trxbh3fc"
        self.positions = [
            ("万千百", (0, 1, 2)), ("万千十", (0, 1, 3)), ("万千个", (0, 1, 4)),
            ("万百十", (0, 2, 3)), ("万百个", (0, 2, 4)), ("万十个", (0, 3, 4)),
            ("千百十", (1, 2, 3)), ("千百个", (1, 2, 4)), ("千十个", (1, 3, 4)),
            ("百十个", (2, 3, 4))
        ]
        self.strategy_map = {
            0: (1, 2), 1: (2, 1), 2: (0, 1), 
            3: (0, 2), 4: (1, 0), 5: (2, 0)
        }

    def fetch_data(self, target_date_str: str, target_limit: int = 100):
        try:
            parsed_url = urlparse(self.api_url)
            headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json, text/plain, */*"}
            query_params = parse_qs(parsed_url.query)
            size_key = 'pageSize'
            for k in ["pageSize", "limit", "count", "rows"]:
                if k in query_params: size_key = k; break
            
            is_new_api = "qqtj666.com" in parsed_url.netloc
            if is_new_api and 'rows' not in query_params: size_key = 'rows'

            all_extracted_data = []
            current_page = 1
            current_date = datetime.strptime(target_date_str, "%Y-%m-%d")
            days_back = 0  

            while len(all_extracted_data) < target_limit and days_back < 30:
                needed = target_limit - len(all_extracted_data)
                current_page_size = min(100, needed)
                req_path = parsed_url.path
                current_date_str = current_date.strftime("%Y-%m-%d")
                
                if is_new_api:
                    if req_path.endswith("/draw-result"): req_path += "-by-datetime"
                    query_params['start_time'] = [f"{current_date_str} 00:00:00"]
                    query_params['end_time'] = [f"{current_date_str} 23:59:59"]
                    query_params['page'] = [str(current_page)]
                    query_params[size_key] = [str(current_page_size)]
                else:
                    query_params['date'] = [current_date_str]
                    query_params['page'] = [str(current_page)]
                    query_params[size_key] = [str(current_page_size)]

                new_query = urlencode(query_params, doseq=True)
                req_url = urlunparse((parsed_url.scheme, parsed_url.netloc, req_path, parsed_url.params, new_query, parsed_url.fragment))
                response = requests.get(req_url, headers=headers, timeout=15, verify=False)
                
                if response.status_code != 200:
                    if len(all_extracted_data) == 0: return False, f"HTTP {response.status_code}: 数据请求失败"
                    break 

                page_data = []
                try:
                    json_data = response.json()
                    def find_data_list(obj):
                        if isinstance(obj, list): return obj
                        if isinstance(obj, dict):
                            for k in ["data", "list", "rows", "history", "records"]:
                                if k in obj and isinstance(obj[k], list): return obj[k]
                            for v in obj.values():
                                res = find_data_list(v)
                                if res: return res
                        return []
                    
                    items = find_data_list(json_data)
                    for it in items:
                        val_number = ""
                        val_issue = ""
                        
                        if isinstance(it, dict):
                            for ik in ["issue", "expect", "period", "drawIssue", "preDrawIssue", "turnNum"]:
                                if ik in it:
                                    val_issue = str(it[ik])
                                    break
                            
                            for k in ["winning_number", "number", "code", "opencode", "drawResult", "preDrawCode", "drawCode"]:
                                if k in it:
                                    val_number = str(it[k])
                                    break
                            if not val_number:
                                for k, v in it.items():
                                    v_str = str(v).replace(",", "").replace("|", "").strip()
                                    if re.fullmatch(r'\d{5}', v_str):
                                        val_number = v_str
                                        break
                        else:
                            val_number = str(it)
                        
                        clean_val = val_number.replace(",", "").replace("|", "").strip()
                        num_match = re.search(r'(?<!\d)\d{5}(?!\d)', clean_val)
                        if num_match: 
                            page_data.append({
                                "issue": val_issue,
                                "number": num_match.group()
                            })

                except Exception as e:
                    error_snippet = response.text[:80].replace('\n', ' ')
                    return False, f"接口返回非预期的格式。片段: {error_snippet}"

                if not page_data:
                    current_date -= timedelta(days=1)
                    current_page = 1
                    days_back += 1
                    continue

                all_extracted_data.extend(page_data)
                if len(page_data) < current_page_size:
                    current_date -= timedelta(days=1)
                    current_page = 1
                    days_back += 1
                else:
                    current_page += 1

            if all_extracted_data:
                if len(all_extracted_data) > target_limit:
                    all_extracted_data = all_extracted_data[:target_limit]
                all_extracted_data.reverse() 
                return True, all_extracted_data
            return False, "接口返回为空，未提取到有效数据"
        except Exception as e:
            return False, f"网络请求异常: {str(e)}"

    def run_analysis(self, history_data, strategy_idx, alert_threshold):
        stats_list = [{"wins": 0, "max_miss": 0, "curr_miss": 0, "is_alert": False} for _ in range(10)]
        history_records = [] 
        
        if len(history_data) < 2: 
            return {"stats": stats_list, "records": history_records, "total_p": 0}
            
        idx_kill_first, idx_kill_sum = self.strategy_map.get(strategy_idx, (1, 2))

        for i in range(1, len(history_data)):
            prev_num = history_data[i-1]["number"]
            curr_item = history_data[i]
            curr_num = curr_item["number"]
            
            display_issue = curr_item["issue"] if curr_item["issue"] else f"第{i+1}期"

            period_record = {
                "period": display_issue,
                "number": curr_num[:5],
                "results": []
            }

            for j, (pos_name, p_idx) in enumerate(self.positions):
                kill_first_val = int(prev_num[p_idx[idx_kill_first]])  
                kill_sum_val = int(prev_num[p_idx[idx_kill_sum]])    
                d1, d2, d3 = int(curr_num[p_idx[0]]), int(curr_num[p_idx[1]]), int(curr_num[p_idx[2]])
                is_win = (d1 != kill_first_val) and (((d1 + d2) % 10 != kill_sum_val) and ((d1 + d3) % 10 != kill_sum_val) and ((d2 + d3) % 10 != kill_sum_val))
                
                period_record["results"].append(is_win)
                
                if is_win:
                    stats_list[j]["wins"] += 1
                    stats_list[j]["curr_miss"] = 0
                else:
                    stats_list[j]["curr_miss"] += 1
                    if stats_list[j]["curr_miss"] > stats_list[j]["max_miss"]:
                        stats_list[j]["max_miss"] = stats_list[j]["curr_miss"]
                        
            history_records.append(period_record)
        
        for j in range(10):
            if stats_list[j]["curr_miss"] >= alert_threshold: stats_list[j]["is_alert"] = True
            
        return {
            "stats": stats_list, 
            "records": history_records, 
            "total_p": len(history_data) - 1
        }

    def generate_bet_numbers(self, last_num, strategy_idx):
        results = []
        idx_kill_first, idx_kill_sum = self.strategy_map.get(strategy_idx, (1, 2))
        for i, (pos_name, p_idx) in enumerate(self.positions):
            kill_first_val = int(last_num[p_idx[idx_kill_first]]) 
            kill_sum_val = int(last_num[p_idx[idx_kill_sum]])   
            valid_nums = []
            for d1 in range(10):
                if d1 == kill_first_val: continue 
                for d2 in range(10):
                    for d3 in range(10):
                        if (d1 + d2) % 10 == kill_sum_val or (d1 + d3) % 10 == kill_sum_val or (d2 + d3) % 10 == kill_sum_val: continue
                        valid_nums.append(f"{d1}{d2}{d3}")
            results.append({"pos_name": pos_name, "count": len(valid_nums), "numbers": " ".join(valid_nums)})
        return results


# ==========================================
# --- UI 主程序 ---
# ==========================================
def main(page: ft.Page):
    page.title = "三星杀号旗舰版"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.scroll = ft.ScrollMode.AUTO 
    page.padding = ft.Padding(left=15, top=40, right=15, bottom=15)
    page.window.width = 420  
    page.window.height = 850
    page.bgcolor = ft.Colors.BLUE_GREY_50 

    engine = LotteryEngine()

    auto_update_flag = False
    last_latest_data = None  
    current_fetched_data = []  # ⚠️ 新增：全局缓存已拉取的数据，用于无缝切换策略

    # --- 1. 顶部标题 ---
    title = ft.Text("🏆 三星杀号数据监控", size=24, weight=ft.FontWeight.BOLD, color=ft.Colors.BLUE_800)
    status_text = ft.Text("请点击同步获取最新数据", color=ft.Colors.GREY_600, size=13)

    # --- 2. 设置区 ---
    strategy_dropdown = ft.Dropdown(
        label="🎯 选择杀号策略",
        options=[
            ft.dropdown.Option("0", "策略1: 第2位杀首, 第3位杀合"),
            ft.dropdown.Option("1", "策略2: 第3位杀首, 第2位杀合"),
            ft.dropdown.Option("2", "策略3: 第1位杀首, 第2位杀合"),
            ft.dropdown.Option("3", "策略4: 第1位杀首, 第3位杀合"),
            ft.dropdown.Option("4", "策略5: 第2位杀首, 第1位杀合"),
            ft.dropdown.Option("5", "策略6: 第3位杀首, 第1位杀合")
        ],
        value="0", expand=True, dense=True
    )
    alert_dropdown = ft.Dropdown(
        label="连挂预警",
        options=[ft.dropdown.Option(str(i), f"{i}期") for i in range(1, 7)],
        value="2", width=100, dense=True
    )
    date_input = ft.TextField(label="同步日期", value=datetime.now().strftime("%Y-%m-%d"), expand=True, dense=True)
    limit_input = ft.TextField(label="统计期数", value="100", width=80, dense=True)
    display_limit_input = ft.TextField(label="显示期数", value="10", width=80, dense=True)

    # --- 3. 历史记录表 ---
    def make_cell(text, width, text_color=ft.Colors.BLACK, weight=ft.FontWeight.NORMAL):
        return ft.Container(
            content=ft.Text(text, size=13, color=text_color, weight=weight, text_align=ft.TextAlign.CENTER),
            width=width, alignment=ft.Alignment(0, 0), padding=ft.Padding(left=0, right=0, top=10, bottom=10)
        )

    header_container = ft.Container(
        content=ft.Row(
            spacing=0,
            controls=[
                make_cell("期数", 85, weight=ft.FontWeight.BOLD), 
                make_cell("开奖号", 60, weight=ft.FontWeight.BOLD),
            ] + [make_cell(p[0], 55, weight=ft.FontWeight.BOLD) for p in engine.positions]
        ),
        bgcolor=ft.Colors.GREY_200, 
        border=ft.Border(bottom=ft.BorderSide(1, ft.Colors.GREY_400))
    )

    history_list_view = ft.Column(spacing=0)

    history_container = ft.Container(
        content=ft.Row(
            scroll=ft.ScrollMode.ALWAYS,
            controls=[
                ft.Column(width=695, spacing=0, controls=[header_container, history_list_view])
            ]
        ),
        border=ft.Border(
            top=ft.BorderSide(1, ft.Colors.GREY_300),
            bottom=ft.BorderSide(1, ft.Colors.GREY_300),
            left=ft.BorderSide(1, ft.Colors.GREY_300),
            right=ft.BorderSide(1, ft.Colors.GREY_300)
        ), 
        border_radius=8, bgcolor=ft.Colors.WHITE, clip_behavior=ft.ClipBehavior.HARD_EDGE 
    )
    
    trend_title = ft.Text("📝 最新开奖与中挂走势", weight=ft.FontWeight.BOLD, size=16, color=ft.Colors.BLUE_800)

    # --- 4. 统计与大底区 ---
    stats_view = ft.ResponsiveRow(run_spacing=10) 
    stats_container = ft.Container(
        content=stats_view, 
        border=ft.Border(
            top=ft.BorderSide(1, ft.Colors.GREY_300),
            bottom=ft.BorderSide(1, ft.Colors.GREY_300),
            left=ft.BorderSide(1, ft.Colors.GREY_300),
            right=ft.BorderSide(1, ft.Colors.GREY_300)
        ),
        border_radius=8, padding=10, bgcolor=ft.Colors.WHITE
    )

    bets_view = ft.ResponsiveRow(run_spacing=10) 

    # --- 5. 核心交互事件 ---
    def copy_to_clipboard(e):
        try:
            text_to_copy = str(e.control.data["text"])
            pos_name = str(e.control.data["pos_name"])
            
            copied = False
            if hasattr(e.page, 'clipboard') and hasattr(e.page.clipboard, 'set_data'):
                try:
                    e.page.clipboard.set_data(text_to_copy)
                    copied = True
                except: pass
            
            if not copied and hasattr(e.page, 'set_clipboard'):
                try:
                    e.page.set_clipboard(text_to_copy)
                    copied = True
                except: pass
            
            if not copied:
                import sys, subprocess
                try:
                    if sys.platform == 'win32':
                        subprocess.run(['clip'], input=text_to_copy.encode('gbk', errors='ignore'), check=True)
                    elif sys.platform == 'darwin':
                        subprocess.run(['pbcopy'], input=text_to_copy.encode('utf-8'), check=True)
                    else:
                        subprocess.run(['xclip', '-selection', 'clipboard'], input=text_to_copy.encode('utf-8'), check=True)
                except Exception as sys_e:
                    print(f"原生剪贴板调用失败: {sys_e}")

            try:
                snack = ft.SnackBar(
                    content=ft.Text(f"✅ [{pos_name}] 复制成功！", color=ft.Colors.WHITE),
                    bgcolor=ft.Colors.GREEN_700,
                    duration=2000
                )
                if hasattr(e.page, "open"):
                    e.page.open(snack)
                else:
                    e.page.snack_bar = snack
                    snack.open = True
                    e.page.update()
            except: pass

            original_text = e.control.text
            original_icon = e.control.icon
            
            e.control.text = "已复制!"
            e.control.icon = ft.Icons.CHECK
            e.control.update()
            
            def reset_btn():
                time.sleep(1.5)
                e.control.text = original_text
                e.control.icon = original_icon
                e.control.update()
                
            threading.Thread(target=reset_btn, daemon=True).start()

        except Exception as ex:
            print(f"复制异常: {ex}")
            e.control.text = "复制失败"
            e.control.icon = ft.Icons.ERROR
            e.control.update()
            def reset_err_btn():
                time.sleep(1.5)
                e.control.text = "一键复制"
                e.control.icon = ft.Icons.COPY_ALL
                e.control.update()
            threading.Thread(target=reset_err_btn, daemon=True).start()

    # ⚠️ 新增：抽取出来的统一 UI 渲染函数 (供请求和切换策略时调用)
    def update_dashboard(e=None):
        if not current_fetched_data:
            return  # 如果还没有数据，就不更新

        try:
            strat_idx = int(strategy_dropdown.value)
            alert_th = int(alert_dropdown.value)
            # 防止用户输入空字符报错
            display_limit_str = display_limit_input.value.strip()
            display_limit = int(display_limit_str) if display_limit_str.isdigit() else 10
        except ValueError:
            return

        analysis = engine.run_analysis(current_fetched_data, strat_idx, alert_th)
        bets = engine.generate_bet_numbers(current_fetched_data[-1]["number"], strat_idx)

        # 动态获取当前选中的策略名称
        strat_name = next((opt.text for opt in strategy_dropdown.options if opt.key == strategy_dropdown.value), "未知策略")

        # 1. 更新标题，将策略名称放入括号中
        trend_title.value = f"📝 最新{display_limit}期开奖与中挂走势 ({strat_name})"

        # 2. 更新历史走势图
        history_list_view.controls.clear()
        display_records = analysis['records'][-display_limit:] if display_limit > 0 else analysis['records']
        for i, rec in enumerate(display_records):
            bg = ft.Colors.WHITE if i % 2 == 0 else ft.Colors.GREY_50 
            cells = [
                make_cell(rec['period'], 85, text_color=ft.Colors.GREY_700),
                make_cell(rec['number'], 60, weight=ft.FontWeight.BOLD),
            ]
            for is_win in rec['results']:
                t_color = ft.Colors.GREEN_600 if is_win else ft.Colors.RED_600
                t_text = "√" if is_win else "X"
                cells.append(make_cell(t_text, 55, text_color=t_color, weight=ft.FontWeight.BOLD))
            
            history_list_view.controls.append(
                ft.Container(
                    content=ft.Row(controls=cells, spacing=0), 
                    bgcolor=bg, 
                    border=ft.Border(bottom=ft.BorderSide(1, ft.Colors.GREY_100))
                )
            )

        # 3. 更新遗漏统计
        stats_view.controls.clear()
        total_p = analysis["total_p"]
        for i, stat in enumerate(analysis["stats"]):
            pos_name = engine.positions[i][0]
            acc_rate = (stat['wins'] / total_p * 100) if total_p > 0 else 0
            
            is_alert = stat['is_alert']
            bg_color = ft.Colors.RED_50 if is_alert else ft.Colors.GREY_50
            miss_color = ft.Colors.RED_700 if is_alert else ft.Colors.BLACK
            miss_weight = ft.FontWeight.BOLD if is_alert else ft.FontWeight.NORMAL

            border_color = ft.Colors.RED_200 if is_alert else ft.Colors.GREY_200
            
            stat_card = ft.Container(
                col={"xs": 6, "sm": 6},
                padding=10, border_radius=8, bgcolor=bg_color,
                border=ft.Border(
                    top=ft.BorderSide(1, border_color),
                    bottom=ft.BorderSide(1, border_color),
                    left=ft.BorderSide(1, border_color),
                    right=ft.BorderSide(1, border_color)
                ),
                content=ft.Column([
                    ft.Row([
                        ft.Text(pos_name, weight=ft.FontWeight.BOLD, size=14),
                        ft.Container(
                            padding=ft.Padding(left=6, right=6, top=2, bottom=2), 
                            border_radius=4,
                            bgcolor=ft.Colors.RED_100 if is_alert else ft.Colors.TRANSPARENT,
                            content=ft.Text(f"漏 {stat['curr_miss']}", color=miss_color, weight=miss_weight, size=12)
                        )
                    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    ft.Text(f"准: {acc_rate:.1f}% | 挂: {stat['max_miss']}", size=12, color=ft.Colors.GREY_700)
                ], spacing=4)
            )
            stats_view.controls.append(stat_card)

        # 4. 更新大底
        bets_view.controls.clear()
        for bet in bets:
            card = ft.Card(
                elevation=2,
                col={"xs": 6, "sm": 6}, 
                content=ft.Container(
                    padding=10,
                    content=ft.Column([
                        ft.Row([
                            ft.Text(bet['pos_name'], weight=ft.FontWeight.BOLD, size=15),
                            ft.Text(f"{bet['count']}注", color=ft.Colors.RED_600, weight=ft.FontWeight.BOLD)
                        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        ft.TextField(
                            value=bet['numbers'], read_only=True, multiline=True, 
                            max_lines=3, min_lines=3, text_size=12, content_padding=8
                        ),
                        ft.OutlinedButton(
                            "一键复制", 
                            icon=ft.Icons.COPY_ALL, 
                            data={"text": bet['numbers'], "pos_name": bet['pos_name']},
                            on_click=copy_to_clipboard,
                            style=ft.ButtonStyle(padding=5, shape=ft.RoundedRectangleBorder(radius=5))
                        )
                    ], spacing=8)
                )
            )
            bets_view.controls.append(card)

        # 5. 最后刷新页面
        page.update()

    # ⚠️ 关键动作：将所有输入框和下拉框的 on_change 事件绑定到上面的函数！
    strategy_dropdown.on_change = update_dashboard
    alert_dropdown.on_change = update_dashboard
    display_limit_input.on_change = update_dashboard

    def on_sync_click(e):
        nonlocal last_latest_data, current_fetched_data
        is_auto = (e is None) 

        sync_btn.disabled = True
        sync_btn.text = "🔄 自动请求数据中..." if is_auto else "数据同步与分析中..."
        if not is_auto:
            status_text.value = "正在请求接口，请稍候..."
            status_text.color = ft.Colors.BLUE_600
        page.update()

        try:
            target_date = date_input.value
            target_limit = int(limit_input.value)

            success, data = engine.fetch_data(target_date, target_limit)
            
            if success:
                current_latest_key = f"{data[-1]['issue']}_{data[-1]['number']}" if data else ""

                if is_auto and last_latest_data == current_latest_key:
                    curr_time = datetime.now().strftime("%H:%M:%S")
                    status_text.value = f"🟢 监控中... 最新期: {data[-1]['number'][:5]} (无更新 {curr_time})"
                    status_text.color = ft.Colors.GREEN_700
                    return 

                # ⚠️ 将新拉取的数据保存到全局缓存，供下拉框切换时使用
                last_latest_data = current_latest_key 
                current_fetched_data = data 
                
                status_text.value = f"✅ 成功加载 {len(data)} 期。最新一期: {data[-1]['number'][:5]}"
                status_text.color = ft.Colors.GREEN_700
                
                # 直接调用统一的渲染函数
                update_dashboard()
                    
            else:
                status_text.value = f"❌ 同步失败: {data}"
                status_text.color = ft.Colors.RED_600
                page.update()

        except Exception as ex:
            status_text.value = f"❌ 发生异常: {str(ex)}"
            status_text.color = ft.Colors.RED_600
            page.update()
        finally:
            if not auto_update_flag:
                sync_btn.disabled = False
                sync_btn.text = "🔄 立即同步并分析"
            else:
                sync_btn.disabled = True
                sync_btn.text = "🟢 实时监控运行中..."
            page.update()

    sync_btn = ft.FilledButton(
        "🔄 立即同步并分析", 
        on_click=on_sync_click, 
        style=ft.ButtonStyle(color=ft.Colors.WHITE, bgcolor=ft.Colors.BLUE_700, shape=ft.RoundedRectangleBorder(radius=8)), 
        height=45, expand=True
    )

    # --- 6. 后台监控 ---
    def auto_sync_task():
        while auto_update_flag:
            for _ in range(60): 
                if not auto_update_flag: 
                    return
                time.sleep(1)
            
            if auto_update_flag:
                on_sync_click(None)

    def on_auto_switch_change(e):
        nonlocal auto_update_flag
        auto_update_flag = e.control.value
        
        if auto_update_flag:
            status_text.value = "🟢 实时监控已开启，准备请求数据..."
            status_text.color = ft.Colors.GREEN_700
            page.update()
            
            on_sync_click(None) 
            threading.Thread(target=auto_sync_task, daemon=True).start()
        else:
            status_text.value = "🔴 实时监控已关闭"
            status_text.color = ft.Colors.GREY_600
            sync_btn.disabled = False
            sync_btn.text = "🔄 立即同步并分析"
            page.update()

    auto_switch = ft.Switch(label="开启监控 (60s刷新)", value=False, on_change=on_auto_switch_change)

    # --- 7. 页面拼装 ---
    page.add(
        title, status_text,
        ft.Divider(height=10, color=ft.Colors.TRANSPARENT),
        
        ft.Card(
            elevation=2,
            content=ft.Container(
                padding=15,
                content=ft.Column([
                    ft.Text("⚙️ 配置参数", weight=ft.FontWeight.BOLD, size=16),
                    ft.Row([strategy_dropdown, alert_dropdown]),
                    ft.Row([date_input, limit_input, display_limit_input]),
                    ft.Row([sync_btn]),
                    ft.Row([auto_switch], alignment=ft.MainAxisAlignment.END)
                ], spacing=10)
            )
        ),
        ft.Divider(height=15, color=ft.Colors.TRANSPARENT),

        trend_title,
        history_container, 
        ft.Divider(height=15, color=ft.Colors.TRANSPARENT),
        
        ft.Text("📊 准确率与遗漏统计", weight=ft.FontWeight.BOLD, size=16, color=ft.Colors.BLUE_800),
        stats_container,
        ft.Divider(height=15, color=ft.Colors.TRANSPARENT),
        
        ft.Text("🎯 下期推荐大底 (一键复制)", weight=ft.FontWeight.BOLD, size=16, color=ft.Colors.BLUE_800),
        bets_view,
        
        ft.Divider(height=30, color=ft.Colors.TRANSPARENT)
    )

if __name__ == "__main__":
    ft.run(main)