"""共享工具函数"""
import os
import json
import requests
from urllib.parse import unquote
from dotenv import load_dotenv


def extract_user_info_from_cookies(cookie_str):
    """从 Cookie 中提取用户信息用于设置 localStorage"""
    user_info = {}

    # 解析 lginfo cookie - 它是 URL 编码的 JSON
    for item in cookie_str.split(';'):
        item = item.strip()
        if item.startswith('lginfo='):
            lginfo_value = item[7:]
            lginfo_decoded = unquote(lginfo_value)
            try:
                parsed = json.loads(lginfo_decoded)
                # 确保解析结果是字典类型（防止 JSON 字符串字面量导致 .get() 失败）
                if isinstance(parsed, dict):
                    user_info = parsed
            except json.JSONDecodeError:
                # 如果不是 JSON，尝试解析 key=value&key=value 格式
                for pair in lginfo_decoded.split('&'):
                    if '=' in pair:
                        k, v = pair.split('=', 1)
                        user_info[k] = v
            break

    # 如果没有从 lginfo 获取到，尝试从 addinfo 获取
    if not user_info.get('uid'):
        for item in cookie_str.split(';'):
            item = item.strip()
            if item.startswith('addinfo='):
                # addinfo 格式: uid|username|phone|token
                parts = item[8:].split('|')
                if len(parts) >= 4:
                    user_info = {
                        'uid': int(parts[0]),
                        'username': parts[1],
                        'nickname': parts[1],
                        'bind_phone': parts[2],
                        'token': parts[3]
                    }
                break

    if not user_info.get('token'):
        for item in cookie_str.split(';'):
            item = item.strip()
            if item.startswith('token='):
                user_info['token'] = item[6:]
                break

    return user_info


def _make_account_label(default_label, cookie_str):
    """从 Cookie 中提取用户名，生成带用户名的账号标签"""
    try:
        user_info = extract_user_info_from_cookies(cookie_str)
        if isinstance(user_info, dict):
            name = user_info.get('nickname') or user_info.get('username')
            if name:
                return f"{default_label} ({name})"
    except Exception:
        pass
    return default_label


def validate_cookie(cookie_str):
    """验证 Cookie 是否有效，返回 (is_valid, error_msg)"""
    user_info = extract_user_info_from_cookies(cookie_str)
    token = user_info.get('token') if isinstance(user_info, dict) else None

    if not token:
        return False, "Cookie 中未找到 token"

    task_result = get_task_list(token)
    if task_result is None:
        return False, "无法连接到服务器"
    if task_result.get('errno') != 0:
        errmsg = task_result.get('errmsg', '未知错误')
        return False, f"API 返回错误: {errmsg}"

    return True, None


def get_all_cookies():
    """获取所有账号的 Cookie
    
    如果未配置Cookie但配置了自动登录凭据，返回空字符串占位符
    以便触发自动登录备用方案
    """
    load_dotenv()  # 自动加载 .env 文件（本地测试用）

    cookies_list = []
    single = os.environ.get('ZAIMANHUA_COOKIE')
    if single and single.strip():
        label = _make_account_label('默认账号', single)
        cookies_list.append((label, single))
    i = 1
    while True:
        cookie = os.environ.get(f'ZAIMANHUA_COOKIE_{i}')
        if cookie and cookie.strip():
            label = _make_account_label(f'账号 {i}', cookie)
            cookies_list.append((label, cookie))
            i += 1
        else:
            break
    
    if not cookies_list:
        username = os.environ.get('ZAIMANHUA_USERNAME')
        password = os.environ.get('ZAIMANHUA_PASSWORD')
        if username and username.strip() and password and password.strip():
            cookies_list.append(('默认账号', ''))
    
    max_index = 0
    for key in os.environ.keys():
        if key.startswith('ZAIMANHUA_USERNAME_'):
            try:
                index = int(key.split('_')[-1])
                max_index = max(max_index, index)
            except ValueError:
                continue
    
    for i in range(1, max_index + 1):
        username = os.environ.get(f'ZAIMANHUA_USERNAME_{i}')
        password = os.environ.get(f'ZAIMANHUA_PASSWORD_{i}')
        if username and username.strip() and password and password.strip():
            if i >= len(cookies_list):
                cookies_list.append((f'账号 {i}', ''))
            elif not cookies_list[i][1]:
                pass
    
    return cookies_list


def get_task_list(token):
    """通过 API 获取任务列表"""
    headers = {
        'Authorization': f'Bearer {token}',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://i.zaimanhua.com/',
        'Accept': 'application/json, text/plain, */*',
    }

    try:
        resp = requests.get('https://i.zaimanhua.com/lpi/v1/task/list', headers=headers, timeout=10)
        if resp.status_code == 200:
            return resp.json()
        else:
            print(f"  获取任务列表失败: HTTP {resp.status_code}")
            return None
    except Exception as e:
        print(f"  获取任务列表异常: {e}")
        return None


def extract_tasks_from_response(task_result):
    """从任务 API 响应中提取所有任务列表

    API 响应结构:
    {
        "errno": 0,
        "data": {
            "task": {
                "dayTask": [...],      # 每日任务
                "newUserTask": [...]   # 新用户任务
            },
            "userCurrency": {...}
        }
    }

    任务状态值:
    - status=1: 未完成
    - status=2: 可领取（任务已完成，等待领取奖励）
    - status=3: 已完成（奖励已领取）
    """
    if not task_result or task_result.get('errno') != 0:
        return []

    data = task_result.get('data', {})
    if not isinstance(data, dict):
        return []

    # 尝试从嵌套结构中提取任务
    task_data = data.get('task', {})
    if isinstance(task_data, dict):
        day_tasks = task_data.get('dayTask', [])
        new_user_tasks = task_data.get('newUserTask', [])
        if day_tasks or new_user_tasks:
            all_tasks = (day_tasks or []) + (new_user_tasks or [])
            # 过滤掉非字典类型的项目，防止 'str' object has no attribute 'get' 错误
            return [t for t in all_tasks if isinstance(t, dict)]

    # 回退：尝试其他可能的结构
    if 'list' in data:
        tasks = data.get('list', [])
        return [t for t in tasks if isinstance(t, dict)]
    if 'tasks' in data:
        tasks = data.get('tasks', [])
        return [t for t in tasks if isinstance(t, dict)]

    return []


def print_task_status(cookie_str, label=""):
    """打印当前任务状态（用于调试）"""
    token = None
    user_info = extract_user_info_from_cookies(cookie_str)
    if isinstance(user_info, dict):
        token = user_info.get('token')
    if not token:
        for item in cookie_str.split(';'):
            item = item.strip()
            if item.startswith('token='):
                token = item[6:]
                break

    if not token:
        print(f"  [{label}] 无法获取 token，跳过任务状态检查")
        return

    print(f"\n=== 任务状态 {label} ===")
    task_result = get_task_list(token)

    if task_result:
        print(f"  API 响应: errno={task_result.get('errno')}")
        if task_result.get('errno') == 0:
            tasks = extract_tasks_from_response(task_result)

            if tasks:
                print(f"  任务数量: {len(tasks)}")
                for task in tasks:
                    task_id = task.get('id') or task.get('taskId')
                    task_name = task.get('title') or task.get('name') or task.get('taskName', '未知')
                    task_desc = task.get('desc', '')
                    status = task.get('status', '?')

                    status_desc = {1: '未完成', 2: '可领取', 3: '已完成'}.get(status, f'未知({status})')

                    currency = task.get('currency', {})
                    credits = currency.get('credits', 0) if isinstance(currency, dict) else 0

                    print(f"    - [{task_id}] {task_name}: {status_desc}")
                    if task_desc:
                        print(f"        描述: {task_desc}")
                    if credits:
                        print(f"        奖励: {credits} 积分")
            else:
                data = task_result.get('data', {})
                print(f"  原始数据: {json.dumps(data, ensure_ascii=False)[:500]}")
        else:
            print(f"  API 错误: {task_result.get('errmsg', '未知错误')}")
    else:
        print("  无法获取任务列表")


def claim_task_reward(token, task_id):
    """通过 API 领取单个任务奖励"""
    headers = {
        'Authorization': f'Bearer {token}',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://i.zaimanhua.com/',
        'Accept': 'application/json, text/plain, */*',
        'Content-Type': 'application/json',
    }

    last_result = None

    json_body_endpoints = [
        'https://i.zaimanhua.com/lpi/v1/task/receive',
        'https://i.zaimanhua.com/lpi/v1/task/claim',
        'https://i.zaimanhua.com/lpi/v1/task/get_reward',
    ]

    param_names = ['id', 'taskId', 'task_id']

    for url in json_body_endpoints:
        for param_name in param_names:
            try:
                json_body = {param_name: task_id}
                resp = requests.post(url, headers=headers, json=json_body, timeout=10)
                if resp.status_code == 200:
                    result = resp.json()
                    if result.get('errno') == 0 or result.get('code') == 0:
                        return True, result
                    errmsg = result.get('errmsg', '') or result.get('message', '')
                    if '已领取' in errmsg or '已完成' in errmsg:
                        return True, result
                    last_result = result
            except Exception as e:
                last_result = {'errmsg': str(e)}
                continue

    for param_name in param_names:
        query_urls = [
            f'https://i.zaimanhua.com/lpi/v1/task/receive?{param_name}={task_id}',
            f'https://i.zaimanhua.com/lpi/v1/task/claim?{param_name}={task_id}',
            f'https://i.zaimanhua.com/lpi/v1/task/get_reward?{param_name}={task_id}',
        ]
        for url in query_urls:
            try:
                resp = requests.get(url, headers=headers, timeout=10)
                if resp.status_code == 200:
                    result = resp.json()
                    if result.get('errno') == 0 or result.get('code') == 0:
                        return True, result
                    errmsg = result.get('errmsg', '') or result.get('message', '')
                    if '已领取' in errmsg or '已完成' in errmsg:
                        return True, result
                    last_result = result
            except Exception as e:
                last_result = {'errmsg': str(e)}
                continue

    return False, last_result


def claim_rewards(cookie_str=None):
    """通过 API 领取所有可领取的任务奖励

    任务状态值:
    - status=1: 未完成
    - status=2: 可领取
    - status=3: 已完成
    """
    print("\n=== 领取积分任务 ===")

    token = None
    if cookie_str:
        user_info = extract_user_info_from_cookies(cookie_str)
        if isinstance(user_info, dict):
            token = user_info.get('token')
        if not token:
            for item in cookie_str.split(';'):
                item = item.strip()
                if item.startswith('token='):
                    token = item[6:]
                    break

    if not token:
        print("  无法获取 token，跳过领取")
        return False

    print("尝试通过 API 领取奖励...")
    task_result = get_task_list(token)

    if not task_result or task_result.get('errno') != 0:
        print("  获取任务列表失败")
        return False

    tasks = extract_tasks_from_response(task_result)
    claimed_count = 0
    claimable_count = 0

    for task in tasks:
        task_id = task.get('id') or task.get('taskId')
        task_name = task.get('title') or task.get('name') or task.get('taskName', '未知任务')
        status = task.get('status', 0)

        if status == 2:
            claimable_count += 1
            print(f"  发现可领取任务: {task_name} (ID: {task_id})")

            if task_id:
                success, result = claim_task_reward(token, task_id)
                if success:
                    print(f"    [OK] 领取成功")
                    claimed_count += 1
                else:
                    print(f"    [FAIL] 领取失败")
        elif status == 3:
            print(f"  任务已领取: {task_name} (ID: {task_id})")
        elif status == 1:
            print(f"  任务未完成: {task_name} (ID: {task_id})")

    if claimable_count == 0:
        print("  没有可领取的奖励")
    else:
        print(f"  尝试领取 {claimable_count} 个任务，成功 {claimed_count} 个")

    return True
