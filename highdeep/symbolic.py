"""Exact, resource-bounded rational arithmetic; no eval, imports or calls."""
import ast
from fractions import Fraction

def evaluate(expression):
    if not isinstance(expression,str) or not 1<=len(expression)<=512:
        raise ValueError('Invalid expression length')
    # Reject syntactic nesting early, including parentheses removed by the AST.
    level=0
    for char in expression:
        if char=='(': level+=1
        elif char==')': level-=1
        if level<0 or level>32: raise ValueError('Invalid expression nesting')
    if level: raise ValueError('Invalid expression nesting')
    try:
        tree=ast.parse(expression.strip(),mode='eval')
    except (SyntaxError,RecursionError,ValueError) as exc:
        raise ValueError('Invalid expression') from exc
    if sum(1 for _ in ast.walk(tree))>128:
        raise ValueError('Expression too complex')
    def walk(node,depth=0):
        if depth>32: raise ValueError('Expression too deep')
        if isinstance(node,ast.Constant) and type(node.value) is int:
            value=Fraction(node.value)
        elif isinstance(node,ast.UnaryOp) and isinstance(node.op,(ast.UAdd,ast.USub)):
            x=walk(node.operand,depth+1); value=-x if isinstance(node.op,ast.USub) else x
        elif isinstance(node,ast.BinOp) and isinstance(node.op,(ast.Add,ast.Sub,ast.Mult,ast.Div)):
            a,b=walk(node.left,depth+1),walk(node.right,depth+1)
            if isinstance(node.op,ast.Add): value=a+b
            elif isinstance(node.op,ast.Sub): value=a-b
            elif isinstance(node.op,ast.Mult): value=a*b
            else:
                if not b: raise ValueError('Division by zero')
                value=a/b
        else:
            raise ValueError('Unsupported arithmetic operation')
        if max(abs(value.numerator).bit_length(),value.denominator.bit_length())>256:
            raise ValueError('Arithmetic resource limit')
        return value
    return walk(tree.body)

def verify_answer(answer,expected):
    try: return evaluate(answer)==evaluate(expected)
    except ValueError: return False
