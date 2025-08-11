import torch
import time

# 장치 설정
device_cpu = torch.device("cpu")
device_gpu = torch.device("cuda")

# 테스트용 큰 텐서
size = (10000, 10000)
a_cpu = torch.rand(size, device=device_cpu)
b_cpu = torch.rand(size, device=device_cpu)

a_gpu = torch.rand(size, device=device_gpu)
b_gpu = torch.rand(size, device=device_gpu)

# CPU 연산
start = time.time()
c_cpu = torch.matmul(a_cpu, b_cpu)
torch.cuda.synchronize()  # GPU일 땐 필요하지만, CPU에선 의미 없음
end = time.time()
print(f"CPU matmul: {end - start:.4f} sec")

# GPU 연산
torch.cuda.synchronize()
start = time.time()
c_gpu = torch.matmul(a_gpu, b_gpu)
torch.cuda.synchronize()  # GPU 연산 끝날 때까지 대기
end = time.time()
print(f"GPU matmul: {end - start:.4f} sec")

# 결과 비교
print("결과 동일 여부:", torch.allclose(c_cpu, c_gpu.cpu()))
