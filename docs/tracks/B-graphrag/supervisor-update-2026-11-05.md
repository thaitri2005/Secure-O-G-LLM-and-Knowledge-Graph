# Track B update for the supervisor, 5 November 2026

Tri's final text for anh Tuấn. Evidence: [log](log.md), [E23](../../experiments/E23-simulated-set.md) to [E29](../../experiments/E29-table-mappings-across-reports.md).

---

Anh ơi, em cập nhật Track B (GraphRAG engine và models) tính đến nay ạ.

Nhìn chung Pipeline đã chạy end-to-end. Câu hỏi tra cứu thì RAG thường là đủ, graph chỉ hơn rõ ở câu hỏi cộng dồn qua nhiều ngày trên DDR. Toàn bộ câu hỏi hiện em dùng AI soạn để test thử nên kết quả mang tính tham khảo ạ.

Em có so sánh 3 cách trả lời:

| Cách | |
|---|---|
| Plain RAG (không graph) | Tìm vài đoạn liên quan bằng BM25, lọc theo tên well và ngày báo cáo, rồi model trả lời từ các đoạn đó |
| Fact graph | Plain RAG, cộng thêm các fact cố định của từng well (total depth, casing...) trích từ bảng và bằng LLM |
| Event graph | Mỗi dòng trong bảng operations của DDR là một event (ngày, số giờ, activity code, độ sâu). Model chuyển câu hỏi thành query, code tính kết quả trên graph, rồi model viết câu trả lời. Câu nào không hợp thì quay về plain RAG |

Kết quả (số câu đúng):

| Loại câu hỏi | Tài liệu | Plain RAG | Có graph |
|---|---|---:|---:|
| 31 câu tra cứu một giá trị, bộ của prototype (prototype đạt 23/31) | EOWR | 28/31 | Fact graph 30–31/31 (bộ này đã dùng khi thiết kế fact graph nên số này hơi cao) |
| 40 câu đủ loại: tra cứu, so sánh, không có đáp án | EOWR | 31/40 | Fact graph 31/40 |
| 36 câu, nhiều câu hỏi về 2 well | EOWR | 23/36 | Fact graph 23/36 |
| 26 câu tra cứu theo ngày | DDR | 14/26 | Event graph 17/26 |
| 35 câu cộng dồn qua nhiều ngày, ví dụ tổng giờ theo activity code, non-productive time, độ sâu theo ngày | DDR | Tốt nhất 5/35 | Event graph 22/35 |
| 23 câu cùng loại trên, soạn thêm để kiểm tra lại sau khi em sửa một lỗi của event graph | DDR | 4/23 | Event graph 19/23 |

Findings:

1. Graph chỉ hơn khi đúng loại câu hỏi. Câu tra cứu thì plain RAG có vẻ là đủ: fact graph không hơn bao nhiêu mà còn tốn khoảng 2.5 LLM calls mỗi trang. Câu cộng dồn thì event graph hơn hẳn, vì plain RAG chỉ thấy vài đoạn nên không cộng được qua 27 ngày báo cáo. Nhưng mà mấy câu này em cho AI soạn để hợp với graph, nên chưa biết người dùng có hỏi vậy không.
2. Với DDR, lọc theo ngày báo cáo ổn hơn nhiều: câu tra cứu tăng từ 7/26 lên 14/26 mà không cần thêm lần gọi model nào.
3. Bảng trong report có thể đọc bằng rule, không cần LLM, nhưng ban đầu rule chỉ hợp với report của GRG. Em test thêm trên 5 report khác, có report của tác giả khác và dùng đơn vị mét, với 16 casing string (cỡ ống và độ sâu đặt) đọc tay từ PDF để so. Ban đầu đúng 4/16. Sau khi sửa rule dựa trên một report riêng thì đúng 13/16, không bị sai giá trị.

Đã xong:

- Pipeline từ chunks đến câu trả lời có citation, chạy local trên GPU, không dùng commercial API. Mỗi lần chạy đều log calls, tokens, thời gian để cân nhắc cost.
- Models: Qwen3-8B để trả lời, Qwen3-Embedding-0.6B cho embeddings. Qwen2.5-7B và Llama-3.1-8B bị loại vì từ chối trả lời gần hết (8/31, 10/31).
- Đã chạy thử neo4j-graphrag-python và LightRAG. Cả hai đều không hơn plain RAG nên em chưa chọn cái nào làm base.
- Event graph cho DDR của AK-3, build không cần LLM, khớp với PDF cả 161/161 event.
- File bàn giao: K2 (ontology mỏng kèm rule đọc bảng) và K4 (answer records cho Track C). Lỗi parsing em đã ghi lại cho Track A.

Hạn chế hiện tại:

- Event graph mới chạy trên một well (AK-3) và một loại form, chưa đưa vào Neo4j. Form DDR của các well khác đang parse lỗi nên chưa áp dụng được.
- Bước model viết câu trả lời cuối đôi khi làm sai kết quả đúng mà graph đã tính.
- Câu hỏi so sánh giữa các well trên EOWR vẫn 0/5, và pipeline vẫn trả sai giá trị ở 7/36 câu của bộ 36 câu ở trên.
- Rule đọc bảng chưa test được trên report digital hiện đại của một tác giả hoàn toàn khác. Bảng survey dày và report scan cần Track A cải thiện parsing/OCR.
- Em chưa chạy thử toàn bộ với K1 thật của Track A và các store của Track C.

Em chưa biết người dùng có hỏi các câu cộng dồn theo thời gian như vậy không nữa vì em dùng claude gen thì nó suggest như thế. Hiện em dùng event graph cho loại này và plain RAG cho mấy câu còn lại. Em nghĩ là nếu anh chỉ em specification để em bảo claude gen đỡ câu hỏi để dev chắc cũng được ạ.

Em cảm ơn anh ạ.
