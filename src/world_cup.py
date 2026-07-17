"""
再漫画 2026暑假世界杯转盘抽奖 活动自动化脚本
"""

import os
import sys
import json
import time
import hashlib
import random
import requests
import urllib3
from dotenv import load_dotenv

# 解决Windows GBK编码问题
sys.stdout.reconfigure(encoding='utf-8')

# 禁用SSL警告（某些服务器TLS配置可能有问题）
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = "https://activity.zaimanhua.com/dApi"
SALT_DRAW_LOAD = "z&m$h*_159753twt"
SALT_OTHER = "mH4vj_15521!Jt"


def md5(s):
    return hashlib.md5(s.encode()).hexdigest()


def make_sign(channel="h5", salt=SALT_OTHER, timestamp=None):
    """生成签名: MD5(channel + timestamp + salt)"""
    if timestamp is None:
        timestamp = int(time.time() * 1000)
    raw = channel + str(timestamp) + salt
    return md5(raw), timestamp


def make_sign_params(salt=SALT_OTHER, timestamp=None):
    """生成包含 channel, timestamp, sign 的参数字典"""
    sign, ts = make_sign(salt=salt, timestamp=timestamp)
    return {"channel": "h5", "timestamp": ts, "sign": sign}


def safe_request(method, url, **kwargs):
    """带重试和SSL处理的请求"""
    kwargs.setdefault("timeout", 15)
    kwargs.setdefault("verify", False)
    if "headers" not in kwargs:
        kwargs["headers"] = {}
    kwargs["headers"].setdefault("User-Agent", 
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    max_retries = 2
    for attempt in range(max_retries):
        try:
            resp = requests.request(method, url, **kwargs)
            return resp
        except (requests.exceptions.SSLError, requests.exceptions.ConnectionError) as e:
            if attempt < max_retries - 1:
                time.sleep(2)
                continue
            raise
    return None


def login_and_get_token(username, password):
    """登录并获取token"""
    print(f"\n=== 登录账号: {username[:2]}*** ===")
    pwd_md5 = md5(password)
    data = {"username": username, "passwd": pwd_md5}
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    resp = safe_request(
        "POST",
        "https://account-api.zaimanhua.com/v1/login/passwd",
        data=data,
        headers=headers,
    )
    if resp is None:
        print("[x] 登录请求失败 (网络/SSL错误)")
        return None, None
    if resp.status_code != 200:
        print(f"[x] 登录失败: HTTP {resp.status_code}")
        return None, None

    result = resp.json()
    if result.get("errno") != 0:
        print(f"[x] 登录失败: {result.get('errmsg', '未知错误')}")
        return None, None

    user_data = result.get("data", {}).get("user", {})
    token = user_data.get("token", "")
    if not token:
        print("[x] 登录失败: 未获取到token")
        return None, None

    nickname = user_data.get("nickname", "未知")
    uid = user_data.get("uid", "")
    print(f"[v] 登录成功! 昵称: {nickname}, UID: {uid}")
    return token, nickname


def get_headers(token):
    return {
        "Authorization": f"Bearer {token}",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://activity.zaimanhua.com/world-cup/",
        "Origin": "https://activity.zaimanhua.com",
        "Platform": "h5",
    }


def api_get(endpoint, headers, extra_params=None, salt=SALT_OTHER):
    """GET请求（自动添加签名）"""
    params = make_sign_params(salt=salt)
    if extra_params:
        params.update(extra_params)
    url = BASE_URL + endpoint
    try:
        resp = safe_request("GET", url, headers=headers, params=params)
        if resp is None:
            return None
        if resp.status_code == 200:
            return resp.json()
        print(f"  HTTP {resp.status_code}: {resp.text[:300]}")
    except Exception as e:
        print(f"  请求异常: {e}")
    return None


def api_post(endpoint, headers, json_body=None, extra_params=None, salt=SALT_OTHER):
    """POST请求（自动添加签名）"""
    params = make_sign_params(salt=salt)
    if extra_params:
        params.update(extra_params)
    url = BASE_URL + endpoint
    try:
        resp = safe_request("POST", url, headers=headers, params=params, json=json_body or {})
        if resp is None:
            return None
        if resp.status_code == 200:
            return resp.json()
        print(f"  HTTP {resp.status_code}: {resp.text[:300]}")
    except Exception as e:
        print(f"  POST请求异常: {e}")
    return None


def get_draw_load(token):
    """获取活动状态（drawInfo）：抽奖次数、任务完成情况"""
    headers = get_headers(token)
    result = api_get("/draw/draw_load", headers, salt=SALT_DRAW_LOAD)
    if not result:
        print("[x] 获取活动状态失败")
        return None
    if result.get("errno") != 0:
        print(f"[x] 获取活动状态失败: {result.get('errmsg')}")
        return None
    data = result.get("data", {})
    print(f"\n=== 活动状态 ===")
    print(f"  抽奖次数: {data.get('times', 0)}")
    print(f"  分享任务: {'已完成' if data.get('shareTimes', 0) >= 1 else '未完成'}")
    print(f"  阅读任务: {'已完成' if data.get('readTimes', 0) >= 1 else '未完成'}")
    print(f"  评论任务: {'已完成' if data.get('addComTimes', 0) >= 1 else '未完成'}")
    return data


def do_share_task(token):
    """执行分享任务：/draw/share (GET)"""
    print(f"\n--- 执行分享任务 ---")
    headers = get_headers(token)
    result = api_get("/draw/share", headers)
    if result and result.get("errno") == 0:
        can_draw = result.get("data", {}).get("canDrawTimes", 0)
        print(f"  [v] 分享任务完成! 可抽奖次数: {can_draw}")
        return True
    else:
        errmsg = result.get("errmsg", "未知错误") if result else "无响应"
        print(f"  [x] 分享任务失败: {errmsg}")
        return False


def do_read_task(token):
    """轻量阅读任务：随机一本漫画 → 随机一个章节 → 读2页"""
    print(f"\n--- 执行阅读任务 (轻量版) ---")
    v4_headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": "okhttp/4.9.3",
        "Accept": "application/json, text/plain, */*",
    }

    try:
        resp = safe_request("GET", "https://v4api.zaimanhua.com/app/v1/comic/filter/list",
                           headers=v4_headers,
                           params={"sortType": "2", "status": "0", "cate": "0", "zone": "0", "theme": "0", "page": "1", "size": "20"})
        if not resp or resp.status_code != 200:
            print("  [x] 获取漫画列表失败")
            return False

        data = resp.json()
        if data.get("errno") != 0:
            print(f"  [x] API错误: {data.get('errmsg')}")
            return False

        comic_list = data.get("data", {}).get("comicList") or data.get("data", {}).get("list") or []
        if not comic_list:
            print("  [x] 无可用漫画")
            return False

        comic = random.choice(comic_list)
        comic_id = comic.get("comic_id") or comic.get("id")
        comic_name = comic.get("title") or comic.get("name", "未知")
        print(f"  随机选中漫画: {comic_name} (ID: {comic_id})")

        resp2 = safe_request("GET", f"https://v4api.zaimanhua.com/app/v1/comic/detail/{comic_id}",
                            headers=v4_headers, params={"_v": "2.2.5"})
        if not resp2 or resp2.status_code != 200:
            print("  [x] 获取章节列表失败")
            return False

        detail_data = resp2.json()
        if detail_data.get("errno") != 0:
            print(f"  [x] API错误: {detail_data.get('errmsg')}")
            return False

        comic_info = detail_data.get("data", {}).get("data", {})
        volumes = comic_info.get("chapters") or []
        chapters = []
        for vol in volumes:
            if isinstance(vol, dict) and "data" in vol:
                for ch in vol["data"]:
                    if ch.get("canRead", True):
                        chapters.append(ch)

        if not chapters:
            print("  [x] 无可用章节")
            return False

        chapter = random.choice(chapters)
        cid = chapter.get("chapter_id")
        ct = chapter.get("chapter_title") or f"第{cid}章"
        print(f"  随机选中章节: {ct} (ID: {cid})")

        resp3 = safe_request("GET", f"https://v4api.zaimanhua.com/app/v1/comic/chapter/{comic_id}/{cid}",
                            headers={**v4_headers, "Platform": "h5"}, params={"_v": "2.2.5"})
        if not resp3 or resp3.status_code != 200:
            print("  [x] 获取图片列表失败")
            return False

        ch_data = resp3.json()
        if ch_data.get("errno") != 0:
            print(f"  [x] API错误: {ch_data.get('errmsg')}")
            return False

        inner = ch_data.get("data", {}).get("data", {})
        images = inner.get("page_url_hd") or inner.get("page_url") or []
        if not images:
            print("  [x] 无可用图片")
            return False

        pages_to_read = min(2, len(images))
        for pidx in range(pages_to_read):
            safe_request("GET", images[pidx], headers=v4_headers)

        print(f"  [v] 阅读完成! 读了 {pages_to_read} 页")
        return True

    except Exception as e:
        print(f"  [x] 阅读异常: {e}")
        return False


def do_comment_task(token, nickname=""):
    """执行评论任务：/draw/add_comment (POST)"""
    print(f"\n--- 执行祝福评论任务 ---")

    from comment_plus import COMMENTS
    content = random.choice(COMMENTS)

    headers = get_headers(token)
    body = {"con": content, "source": 2}
    result = api_post("/draw/add_comment", headers, json_body=body)

    if result and result.get("errno") == 0:
        print(f"  [v] 评论发送成功! 内容: {content}")
        return True
    else:
        errmsg = result.get("errmsg", "未知错误") if result else "无响应"
        print(f"  [x] 评论发送失败: {errmsg}")
        return False


def do_lottery_draw(token, times):
    """执行抽奖：/draw/drawing (GET)"""
    headers = get_headers(token)
    results = []

    print(f"\n=== 开始抽奖 (剩余 {times} 次) ===")
    for i in range(times):
        print(f"\n--- 第 {i+1}/{times} 次抽奖 ---")
        result = api_get("/draw/drawing", headers)
        if result and result.get("errno") == 0:
            data = result.get("data", {})
            prize = data.get("prize", {})
            prize_id = data.get("id", "")
            prize_name = prize.get("name", "") or ""
            if not prize_name:
                prize_name = "谢谢参与"
            prize_cate = prize.get("cate", "")

            print(f"  [v] 抽奖成功!")
            print(f"      奖品: {prize_name} (类别: {prize_cate}, ID: {prize_id})")

            results.append({
                "id": prize_id,
                "name": prize_name,
                "cate": prize_cate,
            })
        else:
            errmsg = result.get("errmsg", "抽奖失败") if result else "接口无响应"
            print(f"  [x] 抽奖失败: {errmsg}")
            if result and result.get("errno"):
                if "次数" in errmsg:
                    break
            continue

        if i < times - 1:
            time.sleep(2)

    return results


def print_summary(draw_results):
    """输出抽奖结果汇总"""
    print(f"\n{'='*60}")
    print(f"  抽奖结果汇总")
    print(f"{'='*60}")

    if draw_results:
        print(f"\n  本轮抽奖获得 {len(draw_results)} 个奖品:")
        for i, r in enumerate(draw_results, 1):
            print(f"    {i}. {r['name']} (类别: {r['cate']})")
    else:
        print(f"\n  本轮未获得奖品")

    print(f"\n{'='*60}")


def run_account(username, password, label=""):
    """为单个账号执行活动任务"""
    if label:
        print(f"\n{'='*60}")
        print(f"  账号: {label}")
        print(f"{'='*60}")

    token, nickname = login_and_get_token(username, password)
    if not token:
        return False

    draw_data = get_draw_load(token)
    if not draw_data:
        return False

    times = draw_data.get("times", 0)
    completed_any = False

    if draw_data.get("shareTimes", 0) < 1:
        if do_share_task(token):
            completed_any = True
            time.sleep(1.5)

    if draw_data.get("addComTimes", 0) < 1:
        if do_comment_task(token, nickname):
            completed_any = True
            time.sleep(1.5)

    if draw_data.get("readTimes", 0) < 1:
        if do_read_task(token):
            completed_any = True
            time.sleep(1.5)

    if completed_any:
        print(f"\n--- 任务完成，重新查询活动状态 ---")
        time.sleep(2)
        draw_data = get_draw_load(token)
        if draw_data:
            times = draw_data.get("times", 0)

    draw_results = []
    if times > 0:
        draw_results = do_lottery_draw(token, times)
    else:
        print(f"\n没有可用抽奖次数")

    print_summary(draw_results)
    return True


def get_all_credentials():
    """获取所有配置的账号凭据"""
    creds = []
    username = os.environ.get("ZAIMANHUA_USERNAME")
    password = os.environ.get("ZAIMANHUA_PASSWORD")
    if username and password:
        creds.append(("默认账号", username, password))

    i = 1
    while True:
        u = os.environ.get(f"ZAIMANHUA_USERNAME_{i}")
        p = os.environ.get(f"ZAIMANHUA_PASSWORD_{i}")
        if u and p:
            creds.append((f"账号{i}", u, p))
            i += 1
        else:
            break
    return creds


def main():
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

    creds = get_all_credentials()
    if not creds:
        print("[x] 未找到账号凭据，请检查 .env 文件")
        return False

    all_ok = True
    for idx, (label, username, password) in enumerate(creds):
        ok = run_account(username, password, label)
        if not ok:
            all_ok = False
        if idx < len(creds) - 1:
            print("\n等待 5 秒后切换下一个账号...")
            time.sleep(5)

    print(f"\n{'='*60}")
    if all_ok:
        print("所有账号世界杯活动执行完成！")
    else:
        print("部分账号执行失败，请检查日志")
    print(f"{'='*60}")
    return all_ok


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
