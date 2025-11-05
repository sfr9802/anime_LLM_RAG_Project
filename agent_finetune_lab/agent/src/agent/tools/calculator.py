import operator

class Calculaotr :
    op_map = {
        "+" : operator.add,
        "더하기" : operator.add,
        "-" : operator.sub,
        "빼기" : operator.sub,
        "*" : operator.mul,
        "곱하기" : operator.mul,
        "/" : lambda x, y : x/y if y != 0 else float("inf"),
        "나누기" : lambda x, y : x/y if y != 0 else float("inf"),
        "^" : operator.pow,
        "제곱" : operator.pow
    }
    
    def calcul(self, x : float, op : str, y : float) :
        if op not in self.op_map :
            raise ValueError(f"지원하지 않는 연산자 입니다. {op}")
        return self.op_map[op](x, y)
                
        