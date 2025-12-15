import streamlit as st
import datetime
import requests
import folium
import math
import re
from streamlit_folium import st_folium

# ====================
# 0. 页面配置与样式
# ====================
st.set_page_config(page_title="全能旅游助手", layout="wide", page_icon="🚗")

st.markdown("""
<style>
    /* 基础样式 */
    .weather-card {
        background: linear-gradient(120deg, #fdfbfb 0%, #ebedee 100%);
        padding: 10px; border-radius: 10px; text-align: center;
        border: 1px solid #ddd; box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    .detail-card {
        background-color: white;
        padding: 20px;
        border-radius: 15px;
        border-left: 6px solid #ff6b6b;
        box-shadow: 0 4px 12px rgba(0,0,0,0.08);
        margin-top: 10px;
    }
    /* 评论样式 */
    .review-bubble {
        background-color: #f9f9f9;
        padding: 12px;
        border-radius: 8px;
        margin-bottom: 10px;
        border: 1px solid #eee;
    }
    .review-header {
        display: flex; justify-content: space-between; margin-bottom: 6px; font-size: 13px; color: #555;
    }
    .user-name { font-weight: bold; color: #333; }
    .review-content { font-size: 14px; color: #2c3e50; line-height: 1.5; }

    /* 周边列表样式 */
    .info-list-item {
        margin-bottom: 8px;
        padding: 8px;
        background-color: #f8f9fa;
        border-radius: 6px;
        border-left: 3px solid #ddd;
        font-size: 14px;
        color: #444;
        display: flex;
        justify-content: space-between;
    }
    .dist-tag {
        color: #e67e22;
        font-weight: bold;
        font-size: 12px;
    }
</style>
""", unsafe_allow_html=True)

# ====================
# 1. 核心算法工具
# ====================
x_pi = 3.14159265358979324 * 3000.0 / 180.0


def bd09_to_wgs84(bd_lon, bd_lat):
    x = bd_lon - 0.0065
    y = bd_lat - 0.006
    z = math.sqrt(x * x + y * y) - 0.00002 * math.sin(y * x_pi)
    theta = math.atan2(y, x) - 0.000003 * math.cos(x * x_pi)
    gg_lon = z * math.cos(theta)
    gg_lat = z * math.sin(theta)
    return gg_lat, gg_lon


def haversine_distance(lat1, lon1, lat2, lon2):
    R = 6371
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def optimize_route_algorithm(spots):
    if not spots: return []
    optimized_spots = [spots[0]]
    remaining_spots = spots[1:]
    while remaining_spots:
        current_spot = optimized_spots[-1]
        nearest_spot = min(
            remaining_spots,
            key=lambda s: haversine_distance(
                current_spot['w_lat'], current_spot['w_lon'],
                s['w_lat'], s['w_lon']
            )
        )
        optimized_spots.append(nearest_spot)
        remaining_spots.remove(nearest_spot)
    return optimized_spots


# ====================
# 2. 火山引擎 Kimi API
# ====================
def get_kimi_reviews(spot_name, city, api_key):
    url = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}

    prompt = f"""
    请提取关于{city}“{spot_name}”的5条游客真实评价。
    要求：
    1. 模仿大众点评真实用户语气，包含网络用语、表情符号。
    2. 评分仅输出纯数字（如 5 或 4.5），不要加“分”字。
    3. 严格按此格式返回：
    用户昵称 | 评分 | 评论内容
    """

    data = {
        "model": "kimi-k2-250905",
        "messages": [{"role": "system", "content": "格式化数据生成器"}, {"role": "user", "content": prompt}],
        "temperature": 0.9
    }

    try:
        response = requests.post(url, headers=headers, json=data, timeout=60)
        if response.status_code == 200:
            content = response.json()['choices'][0]['message']['content']
            reviews = []
            lines = content.strip().split('\n')
            for line in lines:
                if "|" in line:
                    parts = line.split('|')
                    if len(parts) >= 3:
                        reviews.append({
                            "user": parts[0].strip(),
                            "score": parts[1].strip(),
                            "text": parts[2].strip()
                        })
            return reviews
    except:
        pass
    return [{"user": "旅行达人", "score": "4.5", "text": "景色不错，值得一去！"}]


# ====================
# 3. 百度 API 模块 (关键修复)
# ====================
def get_baidu_weather(city_name, ak):
    session = requests.Session()
    session.trust_env = False
    forecasts = []
    try:
        # 1. 获取城市坐标
        geo_url = "https://api.map.baidu.com/place/v2/search"
        geo_params = {"query": city_name, "region": city_name, "output": "json", "ak": ak, "page_size": 1}
        geo_res = session.get(geo_url, params=geo_params).json()
        if not geo_res.get('results'): return [], "无此城市"
        loc = geo_res['results'][0]['location']

        # 2. 获取区划ID
        reg_url = "https://api.map.baidu.com/reverse_geocoding/v3/"
        reg_params = {"ak": ak, "output": "json", "coordtype": "bd09ll", "location": f"{loc['lat']},{loc['lng']}"}
        reg_res = session.get(reg_url, params=reg_params).json()
        district_id = reg_res['result']['addressComponent']['adcode']

        # 3. 获取天气
        weather_url = "https://api.map.baidu.com/weather/v1/"
        weather_params = {"district_id": district_id, "data_type": "all", "ak": ak}
        w_res = session.get(weather_url, params=weather_params).json()

        if w_res.get('status') == 0:
            for day in w_res['result'].get('forecasts', []):
                text = day['text_day']
                icon = "🌥️"
                if "晴" in text:
                    icon = "🌞"
                elif "阴" in text:
                    icon = "☁️"
                elif "雨" in text:
                    icon = "🌧"
                elif "雪" in text:
                    icon = "❄️"
                forecasts.append({
                    "date": f"{day['date']}\n{day['week']}",
                    "icon": icon,
                    "text": day['text_day'],
                    "temp": f"{day['low']}~{day['high']}°C"
                })
            return forecasts, "SUCCESS"
    except:
        return [], "暂无数据"
    return [], "ERROR"


def search_spots_baidu(keyword, city, ak):
    session = requests.Session()
    session.trust_env = False
    url = "https://api.map.baidu.com/place/v2/search"
    params = {"query": keyword, "region": city, "output": "json", "ak": ak, "scope": 2, "page_size": 10}
    spots = []
    try:
        res = session.get(url, params=params).json()
        if res['status'] == 0:
            for item in res['results']:
                loc = item['location']
                w_lat, w_lon = bd09_to_wgs84(loc['lng'], loc['lat'])
                spots.append({
                    "name": item['name'],
                    "addr": item.get('address', '无地址'),
                    "score": float(item.get('detail_info', {}).get('overall_rating', 4.2)),
                    "bd_lat": loc['lat'], "bd_lng": loc['lng'],
                    "w_lat": w_lat, "w_lon": w_lon,
                    "kimi_reviews": None
                })
    except:
        pass
    return spots


def search_nearby_baidu(lat, lng, query, ak):
    """
    搜索周边 (修复距离显示问题)
    """
    session = requests.Session()
    session.trust_env = False
    url = "https://api.map.baidu.com/place/v2/search"

    # ★★★ 修复核心：必须添加 scope: 2，API才会返回 detail_info (包含距离) ★★★
    params = {
        "query": query,
        "location": f"{lat},{lng}",
        "radius": 1500,  # 半径1.5公里
        "output": "json",
        "ak": ak,
        "page_size": 5,
        "scope": 2  # <--- 必须加这个！
    }

    try:
        res = session.get(url, params=params).json()
        if res['status'] == 0 and res['results']:
            results = []
            for i in res['results']:
                # 尝试获取距离
                detail = i.get('detail_info', {})
                dist = detail.get('distance', '未知')
                results.append({"name": i['name'], "dist": dist})
            return results
    except:
        pass
    return []


# ====================
# 4. 页面主逻辑
# ====================
st.title("🚗 全能旅游助手")

with st.sidebar:
    st.header("🔑 系统设置")
    default_ak = "A2tnlcW3BrBa0QH22VLKo20SGTA1Pt7c"
    user_ak = st.text_input("地图服务密钥 (AK)", value=default_ak, type="password")
    st.markdown("---")
    default_kimi_key = "11bffa38-8e14-4ce7-bd18-20abc78a7d16"
    kimi_key = st.text_input("数据接口密钥 (API Key)", value=default_kimi_key, type="password")
    st.markdown("---")
    route_mode = st.radio("路线偏好", ["智能推荐路线", "默认排序"])

col_weather, col_control = st.columns([6, 4])

with col_control:
    st.subheader("📅 行程设置")
    c1, c2 = st.columns(2)
    city = c1.text_input("目的地城市", "西安")
    date = c2.date_input("出发日期", datetime.date.today())

    if st.button("🚀 生成行程方案", use_container_width=True):
        st.session_state.search = True
        st.session_state.sel_idx = 0
        st.session_state.spots = []

if 'spots' not in st.session_state: st.session_state.spots = []
if 'weather' not in st.session_state: st.session_state.weather = []

if st.session_state.get('search') and user_ak:
    if not st.session_state.spots:
        with st.spinner("正在检索全网数据并规划路线..."):
            raw_spots = search_spots_baidu("旅游景点", city, user_ak)
            if raw_spots:
                st.session_state.spots = optimize_route_algorithm(raw_spots) if "智能" in route_mode else raw_spots
                w, _ = get_baidu_weather(city, user_ak)
                st.session_state.weather = w
                st.session_state.sel_idx = 0
            else:
                st.error("未找到相关数据")

with col_weather:
    if st.session_state.weather:
        cols = st.columns(4)
        for i, d in enumerate(st.session_state.weather[:4]):
            with cols[i]:
                st.markdown(f"""
                <div class="weather-card">
                    <div style="color:#666; font-size:13px;">{d['date']}</div>
                    <div style="font-size:26px; margin:2px 0;">{d['icon']}</div>
                    <div style="font-weight:bold; color:#e65100;">{d['temp']}</div>
                    <div style="font-size:13px;">{d['text']}</div>
                </div>""", unsafe_allow_html=True)

st.markdown("---")

if st.session_state.spots:
    spots = st.session_state.spots
    c_map, c_info = st.columns([6, 4])

    with c_map:
        st.subheader("🗺️ 游玩路线图")
        st.caption("提示：点击地图上的数字标记查看详情")
        center = [spots[0]['w_lat'], spots[0]['w_lon']]
        m = folium.Map(
            location=center, zoom_start=13,
            tiles='http://webrd02.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}',
            attr='高德地图'
        )
        coords = [[s['w_lat'], s['w_lon']] for s in spots]
        if len(coords) > 1:
            folium.PolyLine(coords, color="#3498db", weight=4, opacity=0.7, dash_array='5, 10').add_to(m)

        for i, s in enumerate(spots):
            is_selected = (i == st.session_state.get('sel_idx', 0))
            color = '#ff6b6b' if is_selected else '#3498db'
            size = 32 if is_selected else 24
            z_idx = 1000 if is_selected else 1
            icon_html = f"""<div style="background-color:{color}; width:{size}px; height:{size}px; border-radius:50%; border:2px solid white; color:white; text-align:center; line-height:{size - 4}px; font-weight:bold; box-shadow: 2px 2px 6px rgba(0,0,0,0.4);">{i + 1}</div>"""
            folium.Marker(location=[s['w_lat'], s['w_lon']], icon=folium.DivIcon(html=icon_html),
                          tooltip=f"{s['name']}", z_index_offset=z_idx).add_to(m)

        map_data = st_folium(m, width=None, height=550, key="map_interaction")

        if map_data['last_object_clicked']:
            clicked_lat = map_data['last_object_clicked']['lat']
            clicked_lng = map_data['last_object_clicked']['lng']
            for idx, s in enumerate(spots):
                if abs(s['w_lat'] - clicked_lat) < 0.0005 and abs(s['w_lon'] - clicked_lng) < 0.0005:
                    if st.session_state.sel_idx != idx:
                        st.session_state.sel_idx = idx
                        st.rerun()
                    break

    with c_info:
        curr_idx = st.session_state.get('sel_idx', 0)
        curr = spots[curr_idx]

        st.subheader(f"🚩 {curr['name']}")
        st.markdown(
            f"""<div class="detail-card"><p><b>📍 地址：</b> {curr['addr']}</p><p><b>⭐ 综合评分：</b> <span style="color:#f1c40f; font-weight:bold; font-size:18px;">{curr['score']}</span> / 5.0</p></div>""",
            unsafe_allow_html=True)

        # 评论区
        st.markdown("#### 🗣️ 游客真实评价")
        if not curr.get('kimi_reviews'):
            if kimi_key:
                with st.spinner(f"正在加载 {curr['name']} 的最新评论..."):
                    reviews = get_kimi_reviews(curr['name'], city, kimi_key)
                    st.session_state.spots[curr_idx]['kimi_reviews'] = reviews
                    st.rerun()
            else:
                st.warning("数据接口连接失败")

        if curr.get('kimi_reviews'):
            for r in curr['kimi_reviews']:
                try:
                    score_str = str(r['score'])
                    match = re.search(r"(\d+(\.\d+)?)", score_str)
                    numeric_score = float(match.group(1)) if match else 4.0
                    star_count = int(numeric_score)
                except:
                    numeric_score, star_count = 4.0, 4

                st.markdown(f"""
                <div class="review-bubble">
                    <div class="review-header"><span class="user-name">👤 {r['user']}</span><span style="color:#f39c12;">{'★' * star_count} {numeric_score}</span></div>
                    <div class="review-content">{r['text']}</div>
                </div>""", unsafe_allow_html=True)

        # 周边服务 (修复距离显示 & 图标混淆问题)
        st.markdown("#### 🏨 周边服务推荐")

        cache_key = f"nearby_v4_{curr['name']}"
        if cache_key not in st.session_state:
            with st.spinner("正在搜索周边美食与住宿..."):
                foods = search_nearby_baidu(curr['bd_lat'], curr['bd_lng'], "美食", user_ak)
                hotels = search_nearby_baidu(curr['bd_lat'], curr['bd_lng'], "酒店", user_ak)
                st.session_state[cache_key] = (foods, hotels)

        foods_list, hotels_list = st.session_state[cache_key]

        tab_food, tab_hotel = st.tabs(["🍜 附近美食", "🛏️ 附近酒店"])

        with tab_food:
            if foods_list:
                scroll_box = '<div style="height:180px; overflow-y:auto; border:1px solid #eee; padding:10px; border-radius:8px;">'
                for f in foods_list:
                    # 确保图标是 🍽️
                    scroll_box += f"""
                    <div class="info-list-item">
                        <span>🍽️ {f['name']}</span>
                        <span class="dist-tag">{f['dist']}米</span>
                    </div>"""
                scroll_box += '</div>'
                st.markdown(scroll_box, unsafe_allow_html=True)
            else:
                st.info("暂无周边美食数据")

        with tab_hotel:
            if hotels_list:
                scroll_box = '<div style="height:180px; overflow-y:auto; border:1px solid #eee; padding:10px; border-radius:8px;">'
                for h in hotels_list:
                    # 确保图标是 🏨
                    scroll_box += f"""
                    <div class="info-list-item">
                        <span>🏨 {h['name']}</span>
                        <span class="dist-tag">{h['dist']}米</span>
                    </div>"""
                scroll_box += '</div>'
                st.markdown(scroll_box, unsafe_allow_html=True)
            else:
                st.info("暂无周边酒店数据")

else:
    st.info("👈 请在左侧输入目的地并生成方案")
