import streamlit as st
import datetime
import requests
import folium
import math
import random
from streamlit_folium import st_folium

# ====================
# 0. 页面配置与样式
# ====================
st.set_page_config(page_title="百度全能旅游管家 Pro", layout="wide", page_icon="🧳")

st.markdown("""
<style>
    .weather-card {
        background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
        padding: 10px;
        border-radius: 10px;
        text-align: center;
        border: 1px solid #fff;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }
    .weather-icon { font-size: 28px; margin: 5px 0; }
    .weather-temp { font-size: 18px; font-weight: bold; color: #333; }
    .stButton>button { border-radius: 20px; width: 100%; }
    /* 调整 Tab 样式 */
    .stTabs [data-baseweb="tab-list"] { gap: 10px; }
    .stTabs [data-baseweb="tab"] { border-radius: 4px; }
</style>
""", unsafe_allow_html=True)

# ====================
# 1. 核心算法工具
# ====================
x_pi = 3.14159265358979324 * 3000.0 / 180.0

def bd09_to_wgs84(bd_lon, bd_lat):
    """百度坐标转国际坐标"""
    x = bd_lon - 0.0065
    y = bd_lat - 0.006
    z = math.sqrt(x * x + y * y) - 0.00002 * math.sin(y * x_pi)
    theta = math.atan2(y, x) - 0.000003 * math.cos(x * x_pi)
    gg_lon = z * math.cos(theta)
    gg_lat = z * math.sin(theta)
    return gg_lat, gg_lon

def haversine_distance(lat1, lon1, lat2, lon2):
    """计算两点距离 (km)"""
    R = 6371
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1-a))

def optimize_route_algorithm(spots):
    """最短路径贪心算法"""
    if not spots: return []
    optimized = [spots[0]]
    remaining = spots[1:]
    while remaining:
        curr = optimized[-1]
        nearest = min(remaining, key=lambda s: haversine_distance(curr['w_lat'], curr['w_lon'], s['w_lat'], s['w_lon']))
        optimized.append(nearest)
        remaining.remove(nearest)
    return optimized

def generate_smart_packing_list(weather_list):
    """【新功能】根据天气生成行李清单"""
    items = {"必带": ["身份证/学生证", "手机充电器", "充电宝", "纸巾/湿巾"]}
    
    # 分析天气数据
    all_text = "".join([d['text'] for d in weather_list])
    all_temp = [int(d['high_temp']) for d in weather_list]
    min_temp = min([int(d['low_temp']) for d in weather_list]) if weather_list else 20
    
    # 智能推荐
    clothes = []
    gear = []
    
    if "雨" in all_text: gear.append("雨伞/雨衣 ☔")
    if "晴" in all_text and max(all_temp) > 25: gear.append("防晒霜/墨镜 🕶️")
    if min_temp < 15: clothes.append("厚外套/卫衣 🧥")
    elif min_temp < 22: clothes.append("薄外套/长袖 👔")
    else: clothes.append("短袖/透气衣物 👕")
    
    if min_temp > 28: gear.append("小风扇 🎐")
    
    items["衣物建议"] = clothes
    items["装备建议"] = gear
    return items

# ====================
# 2. 百度 API 模块
# ====================
def get_baidu_weather(city_name, ak):
    session = requests.Session()
    session.trust_env = False
    forecasts = []
    try:
        # 1.找城市坐标
        geo_res = session.get("https://api.map.baidu.com/place/v2/search", 
                            params={"query": city_name, "region": city_name, "output": "json", "ak": ak, "page_size": 1}).json()
        if geo_res['status']!=0 or not geo_res['results']: return [], "MOCK"
        loc = geo_res['results'][0]['location']
        
        # 2.找行政区号
        reg_res = session.get("https://api.map.baidu.com/reverse_geocoding/v3/", 
                            params={"ak": ak, "output": "json", "coordtype": "bd09ll", "location": f"{loc['lat']},{loc['lng']}"}).json()
        adcode = reg_res['result']['addressComponent']['adcode']
        
        # 3.查天气
        w_res = session.get("https://api.map.baidu.com/weather/v1/", 
                          params={"district_id": adcode, "data_type": "all", "ak": ak}).json()
        
        if w_res['status'] == 0:
            for day in w_res['result']['forecasts']:
                # 图标逻辑
                t = day['text_day']
                icon = "🌥️"
                if "晴" in t: icon = "🌞"
                elif "雨" in t: icon = "🌧"
                elif "雪" in t: icon = "❄️"
                
                forecasts.append({
                    "date": f"{day['date']} {day['week']}",
                    "icon": icon,
                    "text": t,
                    "temp": f"{day['low']}~{day['high']}°C",
                    "low_temp": day['low'], # 用于计算穿衣
                    "high_temp": day['high']
                })
            return forecasts, "BAIDU"
    except: pass
    return [], "MOCK"

def search_spots_baidu(keyword, city, ak):
    session = requests.Session()
    session.trust_env = False
    spots = []
    try:
        res = session.get("https://api.map.baidu.com/place/v2/search", 
                        params={"query": keyword, "region": city, "output": "json", "ak": ak, "scope": 2, "page_size": 10}).json()
        if res['status'] == 0:
            for item in res['results']:
                loc = item['location']
                w_lat, w_lon = bd09_to_wgs84(loc['lng'], loc['lat'])
                spots.append({
                    "name": item['name'],
                    "addr": item.get('address', '暂无地址'),
                    "score": item.get('detail_info', {}).get('overall_rating', '4.5'),
                    "bd_lat": loc['lat'], "bd_lng": loc['lng'],
                    "w_lat": w_lat, "w_lon": w_lon
                })
    except: pass
    return spots

def search_nearby(lat, lng, query, ak):
    session = requests.Session()
    session.trust_env = False
    try:
        res = session.get("https://api.map.baidu.com/place/v2/search", 
                        params={"query": query, "location": f"{lat},{lng}", "radius": 2000, "output": "json", "ak": ak}).json()
        if res['status'] == 0 and res['results']:
            return " | ".join([i['name'] for i in res['results'][:3]])
    except: pass
    return "暂无推荐"

# ====================
# 3. 主界面
# ====================
st.title("🧳 百度全能旅游管家 Pro")

# --- 侧边栏 ---
with st.sidebar:
    st.header("🔑 设置")
    default_ak = "A2tnlcW3BrBa0QH22VLKo20SGTA1Pt7c"
    user_ak = st.text_input("百度 AK", value=default_ak, type="password")
    
    st.divider()
    st.header("💰 预算计算器")
    budget_traffic = st.number_input("交通预算", 0, 10000, 500)
    budget_hotel = st.number_input("住宿预算", 0, 10000, 800)
    budget_food = st.number_input("餐饮/门票", 0, 10000, 600)
    total = budget_traffic + budget_hotel + budget_food
    st.metric("预计总花费", f"¥ {total}")

# --- 顶部输入 ---
c1, c2, c3 = st.columns([2, 2, 2])
city = c1.text_input("目的地", "杭州")
route_mode = c2.selectbox("路线策略", ["智能最短路径 (推荐)", "百度默认热度"])
if c3.button("🚀 生成全套方案", use_container_width=True):
    st.session_state.search = True
else:
    st.session_state.search = False if 'search' not in st.session_state else st.session_state.search

if 'spots' not in st.session_state: st.session_state.spots = []
if 'weather' not in st.session_state: st.session_state.weather = []

# --- 核心处理 ---
if st.session_state.search and user_ak:
    with st.spinner("正在为您规划最佳路线、查询天气、生成清单..."):
        # 1. 搜景点
        raw = search_spots_baidu("旅游景点", city, user_ak)
        if raw:
            # 2. 路线优化
            st.session_state.spots = optimize_route_algorithm(raw) if "智能" in route_mode else raw
            # 3. 查天气
            w, _ = get_baidu_weather(city, user_ak)
            st.session_state.weather = w
            st.session_state.sel_idx = 0
            st.toast("方案已生成！请查看下方标签页", icon="✅")
        else:
            st.error("未找到景点，请检查AK或城市名")

# --- 天气卡片 ---
if st.session_state.weather:
    st.write(f"🌤️ **{city} 未来天气**")
    cols = st.columns(4)
    for i, d in enumerate(st.session_state.weather[:4]):
        with cols[i]:
            st.markdown(f"""
            <div class="weather-card">
                <div style="font-size:12px;color:#666">{d['date']}</div>
                <div class="weather-icon">{d['icon']}</div>
                <div class="weather-temp">{d['temp']}</div>
                <div style="font-size:13px">{d['text']}</div>
            </div>""", unsafe_allow_html=True)

st.divider()

# --- 下方功能区 (使用 Tabs 分页) ---
if st.session_state.spots:
    spots = st.session_state.spots
    
    tab1, tab2, tab3 = st.tabs(["🗺️ 路线地图", "📋 景点详情", "🧰 智能工具箱"])
    
    # === Tab 1: 地图 ===
    with tab1:
        center = [spots[0]['w_lat'], spots[0]['w_lon']]
        m = folium.Map(location=center, zoom_start=13, tiles="CartoDB positron")
        
        pts = []
        for i, s in enumerate(spots):
            pt = [s['w_lat'], s['w_lon']]
            pts.append(pt)
            color = 'red' if i == st.session_state.get('sel_idx', 0) else 'blue'
            
            # 导航链接
            nav_link = f"https://api.map.baidu.com/marker?location={s['bd_lat']},{s['bd_lng']}&title={s['name']}&content={s['name']}&output=html"
            popup_html = f"""
            <b>{i+1}. {s['name']}</b><br>
            评分: {s['score']}<br>
            <a href="{nav_link}" target="_blank" style="color:blue">📍 去这里 (打开百度地图)</a>
            """
            
            icon_html = f"""<div style="background:{color};color:white;border-radius:50%;width:24px;height:24px;text-align:center;border:2px solid white">{i+1}</div>"""
            folium.Marker(location=pt, popup=popup_html, icon=folium.DivIcon(html=icon_html)).add_to(m)
            
        if len(pts) > 1:
            folium.PolyLine(pts, color="#3498db", weight=4, opacity=0.8).add_to(m)
            
        st_folium(m, width=1200, height=500)
        
        # 距离统计
        dist = sum([haversine_distance(spots[i]['w_lat'], spots[i]['w_lon'], spots[i+1]['w_lat'], spots[i+1]['w_lon']) for i in range(len(spots)-1)])
        st.caption(f"📏 路线总长约: {dist:.1f} km (直线距离)")

    # === Tab 2: 详情 ===
    with tab2:
        cols = st.columns(len(spots))
        for i, s in enumerate(spots):
            if cols[i].button(f"{i+1}.{s['name'][:3]}", key=f"btn_{i}"):
                st.session_state.sel_idx = i
                st.rerun()
                
        curr = spots[st.session_state.get('sel_idx', 0)]
        st.subheader(f"📍 {curr['name']}")
        
        cache = f"nb_{curr['name']}"
        if cache not in st.session_state:
            with st.spinner("查找周边..."):
                f = search_nearby(curr['bd_lat'], curr['bd_lng'], "美食", user_ak)
                h = search_nearby(curr['bd_lat'], curr['bd_lng'], "酒店", user_ak)
                st.session_state[cache] = (f, h)
        
        f_res, h_res = st.session_state[cache]
        c1, c2 = st.columns(2)
        with c1:
            st.info(f"🍜 **美食推荐**: {f_res}")
            st.write(f"🏠 **地址**: {curr['addr']}")
        with c2:
            st.success(f"🏨 **周边住宿**: {h_res}")
            st.write(f"⭐ **评分**: {curr['score']}")

    # === Tab 3: 智能工具箱 (新功能) ===
    with tab3:
        col_list, col_export = st.columns(2)
        
        # 1. 智能行李清单
        with col_list:
            st.subheader("🎒 智能行李清单")
            if st.session_state.weather:
                pack_list = generate_smart_packing_list(st.session_state.weather)
                
                st.markdown("**必带物品:**")
                for item in pack_list["必带"]: st.checkbox(item, value=True, key=f"must_{item}")
                
                st.markdown("**👕 穿衣建议 (基于天气):**")
                for item in pack_list["衣物建议"]: st.checkbox(item, value=True, key=f"cloth_{item}")
                
                if pack_list["装备建议"]:
                    st.markdown("**☔ 装备建议:**")
                    for item in pack_list["装备建议"]: st.checkbox(item, value=True, key=f"gear_{item}")
            else:
                st.warning("暂无天气数据，无法生成建议")

        # 2. 导出行程
        with col_export:
            st.subheader("📥 导出行程单")
            
            # 生成文本内容
            plan_text = f"【{city} 旅游行程单】\n"
            plan_text += f"出发日期: {datetime.date.today()}\n"
            plan_text += f"预计预算: ¥{total}\n\n"
            
            plan_text += "--- ☁️ 天气预报 ---\n"
            for d in st.session_state.weather:
                plan_text += f"{d['date']}: {d['text']} ({d['temp']})\n"
            
            plan_text += "\n--- 🗺️ 游玩路线 ---\n"
            for i, s in enumerate(spots):
                plan_text += f"第{i+1}站: {s['name']}\n   地址: {s['addr']}\n"
            
            st.text_area("预览", plan_text, height=300)
            
            st.download_button(
                label="📄 下载 TXT 行程单",
                data=plan_text,
                file_name=f"{city}_travel_plan.txt",
                mime="text/plain"
            )
