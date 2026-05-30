# 🚇 Cologne Transit AI

> Ứng dụng tìm tuyến giao thông công cộng cho mạng lưới Cologne (Köln), Đức.
> Backend Python/Flask, frontend Leaflet, dữ liệu OSM và thuật toán A* theo trạng thái `(node_id, current_line)` với phí chuyển tuyến.

---

## 📌 Mô tả dự án

Cologne Transit AI là một hệ thống web full-stack cho phép:

- **Người dùng:** Chọn điểm đi và điểm đến trên bản đồ, hệ thống sẽ tính và hiển thị **lộ trình tối ưu** cùng **chi tiết từng đoạn đi**.
- **Quản trị viên:** Bật/tắt các tuyến `Rail`, `Sub` và `Train` để mô phỏng tình huống bảo trì, sự cố hoặc tuyến bị đóng cửa.

Dữ liệu mạng lưới được xây dựng từ **OpenStreetMap** bởi `osmnx`, bao gồm cả:

- danh sách trạm (`nodes`) với toạ độ địa lý
- danh sách cạnh (`edges`) với độ dài và `geometry` thực tế
- nhiều tuyến qua cùng một cạnh

Hệ thống pathfinding hiện dùng **thuật toán A*** với trạng thái mở rộng là `(node_id, current_line)` để giữ cơ chế **transfer penalty** và đảm bảo đầu ra JSON không đổi.

---

## 🏗️ Cấu trúc dự án

```
CologneTransitAI/
├── backend/
│   ├── app.py          # Flask API server, đồng thời serve frontend
│   └── engine.py       # TransitEngine: load đồ thị, Dijkstra + transfer penalty, toggle tuyến
│
├── frontend/
│   ├── index.html      # Giao diện chính: sidebar + bản đồ Leaflet
│   └── js/
│       ├── api.js          # Hàm gọi API backend (fetch wrapper)
│       └── cologne_map.js  # Leaflet.js: render bản đồ, markers, path, lộ trình
│
├── data/
│   └── cologne_network.json    # Dữ liệu đồ thị OSM (nodes + edges)
│
├── scripts/
│   └── fetch_data.py   # Script thu thập dữ liệu từ OpenStreetMap
│
├── pyproject.toml      # Khai báo project (dùng với uv)
├── requirements.txt    # Danh sách thư viện Python
└── README.md
```

---

## 🚀 Cách chạy dự án

### Yêu cầu
- Python 3.10+
- [uv](https://github.com/astral-sh/uv) (khuyến nghị) hoặc pip

### Bước 1 — Tạo môi trường ảo và cài thư viện

**Dùng `uv` (khuyến nghị — nhanh hơn pip ~10×):**
```powershell
uv venv .venv
uv pip install -r requirements.txt
```

**Hoặc dùng pip truyền thống:**
```bash
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -r requirements.txt
```

> Các thư viện chính: `flask`, `flask-cors`, `networkx`, `osmnx`, `geopandas`

### Bước 2 — Kích hoạt môi trường ảo

```powershell
.venv\Scripts\activate
```

### Bước 3 — Chạy server

```bash
python backend/app.py
```

Server sẽ khởi động tại: **http://localhost:5000**

> Flask tự động serve cả frontend — **không cần** mở file HTML riêng hay cài thêm Live Server.

### Bước 4 — Mở trình duyệt

Truy cập: [http://localhost:5000](http://localhost:5000)

---

## 🎮 Hướng dẫn sử dụng

| Thao tác | Kết quả |
|----------|---------|
| Click vào 1 trạm trên bản đồ | Chọn **điểm đi** (marker xanh lá) |
| Click vào trạm thứ 2 | Chọn **điểm đến** (marker đỏ) → tự động tìm đường |
| Đường đỏ nét đứt xuất hiện | Đường đi ngắn nhất đã được tìm thấy |
| Kéo xuống trong sidebar | Xem **lộ trình chi tiết** (đi tuyến nào, từ đâu đến đâu, bao nhiêu km) |
| Gạt công tắc trong Admin panel | Vô hiệu hóa / kích hoạt tuyến tàu |
| Nhấn ▼/▶ trên nhóm Rail/Sub/Train | Thu gọn / mở rộng danh sách tuyến |
| Nhấn ☀️/🌙 góc phải | Chuyển giao diện sáng / tối |
| Nhấn "Xóa chọn điểm" | Reset lại lựa chọn và lộ trình |

---

## 🎨 Màu sắc tuyến đường

| Loại | Màu | Mô tả |
|------|-----|-------|
| 🔵 **Rail** | `#0085c8` xanh lam | Tuyến có tên đặc biệt (Innenstadttunnel, SB-Nord…) |
| 🟢 **Sub** | `#00c666` xanh lá | KVB Stadtbahn — số tuyến 1–99 |
| 🟡 **Train** | `#ffd600` vàng | Tàu khu vực Regional — số 4 chữ số (26xx, 74xx…) |
| 🔴 **Đường ngắn nhất** | `#f44336` đỏ | Kết quả pathfinding (nét đứt) |

---

## 🛠️ Công nghệ sử dụng

| Thành phần | Công nghệ |
|-----------|-----------|
| Backend API | Python 3.10+, Flask, Flask-CORS |
| Thuật toán đồ thị | Custom A* với trạng thái `(node_id, current_line)` và Transfer Penalty |
| Thuật toán heuristic | Haversine distance để ước lượng khoảng cách trực tiếp đến đích |
| Thu thập dữ liệu OSM | OSMnx, GeoPandas |
| Frontend Map | Leaflet.js với bản đồ CARTO dark/light |
| Giao diện | HTML + Vanilla CSS (Flex layout, Dark/Light mode) |
| Fonts | Google Fonts — Inter |
| Package manager | uv |

---

## 🧠 Thuật toán Pathfinding

Hệ thống hiện sử dụng **thuật toán A*** trên không gian trạng thái `(node_id, current_line)` để vừa giữ chi phí chuyển tuyến, vừa tận dụng heuristic địa lý.

- **State space**: mỗi trạm được mô tả bởi trạng thái hiện tại của tuyến đang đi.
- **Chi phí thực tế (g(n))**: tổng độ dài cạnh + **TRANSFER_PENALTY = 300m** mỗi khi đổi tuyến.
- **Heuristic (h(n))**: khoảng cách Haversine giữa trạm hiện tại và trạm đích.
- **Ưu tiên**: `f(n) = g(n) + h(n)` giúp A* mở rộng các trạng thái gần đích trước.

### Tại sao A* và không đổi cấu trúc đường đi

- Giữ nguyên đầu ra JSON của `/api/find-path` và cấu trúc `details`.
- Vẫn xử lý đúng `disabled lines`, `line classification`, `route history` và `geometry reconstruction`.
- Không thay đổi schema hoặc cách đường đi được tái tạo từ các cạnh.

### 🔍 Ưu điểm của heuristic Haversine

Heuristic Haversine là **admissible** vì:

- Nó là khoảng cách thẳng giữa hai toạ độ địa lý;
- Mạng lưới đường sắt không thể ngắn hơn đường thẳng này;
- Nó không tính thêm penalty chuyển tuyến, nên luôn là một lower bound cho chi phí còn lại.

### ⚡ Hiệu suất

- Trong trường hợp xấu nhất, A* vẫn có độ phức tạp O(E + V log V) với heap, giống Dijkstra.
- Heuristic Haversine giúp giảm số trạng thái mở rộng so với tìm kiếm không có hướng dẫn.
- Khi start/end cách xa nhau, A* tập trung mở rộng các nhánh tiến về đích và cắt tỉa nhiều đường không cần thiết.

---

## 📡 API Endpoints

| Method | Endpoint | Mô tả |
|--------|----------|-------|
| `GET` | `/api/network` | Lấy toàn bộ nodes + edges (kèm `line_type`) |
| `GET` | `/api/lines` | Lấy danh sách tuyến `{name, type}` + tuyến đang bị tắt |
| `POST` | `/api/find-path` | Tìm đường ngắn nhất (`start_node`, `end_node`) |
| `POST` | `/api/admin/toggle-line` | Bật/tắt tuyến tàu (`line`, `disabled`) |

---

## 👥 Môn học

**IT3160 - Introduction to AI** — Hanoi University of Science and Technology (HUST), 2025.2
