import requests
import re
import urllib3
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from datetime import datetime, timedelta

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class LotteryEngine:
    def __init__(self):
        # 已更新为哈希三分彩 API
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

            all_extracted_numbers = []
            current_page = 1
            current_date = datetime.strptime(target_date_str, "%Y-%m-%d")
            days_back = 0  

            while len(all_extracted_numbers) < target_limit and days_back < 30:
                needed = target_limit - len(all_extracted_numbers)
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
                    if len(all_extracted_numbers) == 0: return False, f"HTTP {response.status_code}: 数据请求失败"
                    break 

                page_numbers = []
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
                        val = ""
                        if isinstance(it, dict):
                            # 1. 尝试常见的开奖号字段名（增加了 drawCode 等）
                            for k in ["winning_number", "number", "code", "opencode", "drawResult", "preDrawCode", "drawCode"]:
                                if k in it:
                                    val = str(it[k])
                                    break
                            
                            # 2. 如果没找到，自动在整行数据里寻找长得像开奖号的值
                            if not val:
                                for k, v in it.items():
                                    v_str = str(v).replace(",", "").replace("|", "").strip()
                                    # 必须严格等于5个数字，这能完美避开十几位的期号干扰
                                    if re.fullmatch(r'\d{5}', v_str):
                                        val = v_str
                                        break
                        else:
                            val = str(it)
                        
                        # 清洗数据并严格提取（只提取前后没有其他数字的 5 位数）
                        clean_val = val.replace(",", "").replace("|", "").strip()
                        num_match = re.search(r'(?<!\d)\d{5}(?!\d)', clean_val)
                        if num_match: 
                            page_numbers.append(num_match.group())
                            
                except Exception as e:
                    # 如果网页打不开，直接报错，不再乱抓数据
                    error_snippet = response.text[:80].replace('\n', ' ')
                    return False, f"接口返回异常 (非JSON数据)。片段: {error_snippet}"

            if all_extracted_numbers:
                if len(all_extracted_numbers) > target_limit:
                    all_extracted_numbers = all_extracted_numbers[:target_limit]
                all_extracted_numbers.reverse() 
                return True, all_extracted_numbers
            return False, "接口返回为空"
        except Exception as e:
            return False, f"异常: {str(e)}"

    def run_analysis(self, history_lines, strategy_idx, alert_threshold):
        stats_list = [{"wins": 0, "max_miss": 0, "curr_miss": 0, "is_alert": False} for _ in range(10)]
        # ⚠️ 新增：专门记录每一期的对错详情
        history_records = [] 
        
        if len(history_lines) < 2: 
            return {"stats": stats_list, "records": history_records, "total_p": 0}
            
        idx_kill_first, idx_kill_sum = self.strategy_map.get(strategy_idx, (1, 2))

        for i in range(1, len(history_lines)):
            prev, curr = history_lines[i-1], history_lines[i]
            
            period_record = {
                "period": f"第{i+1}期",
                "number": curr[:5],
                "results": []
            }

            for j, (pos_name, p_idx) in enumerate(self.positions):
                kill_first_val = int(prev[p_idx[idx_kill_first]])  
                kill_sum_val = int(prev[p_idx[idx_kill_sum]])    
                d1, d2, d3 = int(curr[p_idx[0]]), int(curr[p_idx[1]]), int(curr[p_idx[2]])
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
            "records": history_records, # ⚠️ 返回给界面的详细记录
            "total_p": len(history_lines) - 1
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